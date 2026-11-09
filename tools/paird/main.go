// paird - the tiny service behind AutoSongs' internet pairing.
//
// A phone is given eight characters. It asks this service where the bridge
// that owns those characters is, and is answered with an address and a
// key - but only while that bridge is actually running.
//
// It does three things and nothing else:
//
//	POST /api/paird/bridge/register    a bridge claims its eight characters
//	POST /api/paird/bridge/beat        ...and says it is still running
//	POST /api/paird/bridge/drop        ...and says it is going away
//	POST /api/paird/pair               a phone asks where those characters are
//	POST /api/paird/tunnel/new         a new install asks for a fixed address
//	GET  /api/paird/healthz            is it alive
//
// Everything is in memory plus one small JSON file, because a bridge that is
// not running has no address worth remembering. The whole service is a few
// hundred kilobytes of code and a few megabytes of memory: the song files go
// from the bridge to the phone through Cloudflare and never touch this
// machine, so there is nothing here to scale.
package main

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

const version = "1.0.0"

// ---------------------------------------------------------------- config

type cloudflareConfig struct {
	Token   string `json:"token"`   // an API token: Account.Tunnel:Edit, Zone.DNS:Edit
	Account string `json:"account"` // the account id that owns the tunnels
	Zone    string `json:"zone"`    // the zone id of the domain below
	Prefix  string `json:"prefix"`  // "bridge" -> <slug>.bridge.example.com
}

type config struct {
	Listen          string           `json:"listen"`
	State           string           `json:"state"`
	Cloudflare      cloudflareConfig `json:"cloudflare"`
	PairTTLMinutes  int              `json:"pair_ttl_minutes"`  // how long a code stays resolvable after the last heartbeat
	MaxTunnelsPerIP int              `json:"max_tunnels_per_ip"` // new installs a single address may create per day
	PairPerTenMin   int              `json:"pair_per_ten_minutes"`
}

func defaultConfig() config {
	return config{
		Listen:          "127.0.0.1:8790",
		State:           "/autosongs/paird/state.json",
		PairTTLMinutes:  15,
		MaxTunnelsPerIP: 4,
		PairPerTenMin:   12,
	}
}

func loadConfig(path string) (config, error) {
	cfg := defaultConfig()
	raw, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return cfg, nil
		}
		return cfg, err
	}
	if err := json.Unmarshal(raw, &cfg); err != nil {
		return cfg, err
	}
	if cfg.Listen == "" {
		cfg.Listen = defaultConfig().Listen
	}
	if cfg.PairTTLMinutes <= 0 {
		cfg.PairTTLMinutes = defaultConfig().PairTTLMinutes
	}
	return cfg, nil
}

// ---------------------------------------------------------------- storage

// bridge is one running bridge, reachable at Url for as long as it keeps
// saying so.
type bridge struct {
	Code    string    `json:"code"`
	URL     string    `json:"url"`
	Key     string    `json:"key"`
	IP      string    `json:"ip"`
	Claim   string    `json:"claim"` // sha256 of the secret the bridge keeps; it beats and drops with this
	Expires time.Time `json:"expires"`
	Seen    time.Time `json:"seen"`
}

type tunnel struct {
	Slug      string    `json:"slug"`
	Hostname  string    `json:"hostname"`
	TunnelID  string    `json:"tunnel_id"`
	Token     string    `json:"token"`
	IP        string    `json:"ip"`
	Created   time.Time `json:"created"`
	RotateKey string    `json:"rotate_key"` // lets the install fetch its token again
}

type state struct {
	Bridges map[string]bridge `json:"bridges"`
	Tunnels map[string]tunnel `json:"tunnels"`
}

type store struct {
	mu   sync.Mutex
	path string
	st   state
}

func newStore(path string) *store {
	s := &store{path: path, st: state{
		Bridges: map[string]bridge{},
		Tunnels: map[string]tunnel{},
	}}
	raw, err := os.ReadFile(path)
	if err == nil {
		_ = json.Unmarshal(raw, &s.st)
		if s.st.Bridges == nil {
			s.st.Bridges = map[string]bridge{}
		}
		if s.st.Tunnels == nil {
			s.st.Tunnels = map[string]tunnel{}
		}
	}
	s.expire()
	return s
}

// save writes the whole file, through a temporary one, so a power cut cannot
// leave half a JSON document behind.
func (s *store) save() {
	raw, err := json.MarshalIndent(s.st, "", "  ")
	if err != nil {
		log.Printf("state: %v", err)
		return
	}
	dir := filepath.Dir(s.path)
	_ = os.MkdirAll(dir, 0o755)
	tmp := s.path + ".tmp"
	if err := os.WriteFile(tmp, raw, 0o600); err != nil {
		log.Printf("state: %v", err)
		return
	}
	if err := os.Rename(tmp, s.path); err != nil {
		log.Printf("state: %v", err)
	}
}

func (s *store) expire() {
	now := time.Now().UTC()
	for code, b := range s.st.Bridges {
		if b.Expires.Before(now) {
			delete(s.st.Bridges, code)
		}
	}
}

// ---------------------------------------------------------------- helpers

func randomHex(n int) string {
	buf := make([]byte, n)
	if _, err := rand.Read(buf); err != nil {
		panic(err)
	}
	return hex.EncodeToString(buf)
}

func hashClaim(secret string) string {
	sum := sha256.Sum256([]byte(secret))
	return hex.EncodeToString(sum[:])
}

// clientIP is what the rate limits count. Caddy puts the real address in
// X-Forwarded-For; the socket address is the fallback.
func clientIP(r *http.Request) string {
	if fwd := r.Header.Get("X-Forwarded-For"); fwd != "" {
		first := strings.TrimSpace(strings.Split(fwd, ",")[0])
		if first != "" {
			return first
		}
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

// limiter is a fixed-window counter per address. It exists so eight
// characters cannot be guessed by brute force: a code is 40 bits, and
// without a limit a script would walk through them.
type limiter struct {
	mu     sync.Mutex
	counts map[string]int
	reset  time.Time
	max    int
}

func newLimiter(max int) *limiter {
	return &limiter{counts: map[string]int{}, reset: time.Now().Add(10 * time.Minute), max: max}
}

func (l *limiter) allow(ip string) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	now := time.Now()
	if now.After(l.reset) {
		l.counts = map[string]int{}
		l.reset = now.Add(10 * time.Minute)
	}
	l.counts[ip]++
	return l.counts[ip] <= l.max
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func fail(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

func decode(r *http.Request, into any) error {
	defer r.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(r.Body, 16*1024))
	if err != nil {
		return err
	}
	if len(raw) == 0 {
		return errors.New("empty body")
	}
	return json.Unmarshal(raw, into)
}

func normalizeCode(code string) string {
	var b strings.Builder
	for _, ch := range strings.ToUpper(code) {
		if ch == '-' || ch == ' ' || ch == '\t' {
			continue
		}
		b.WriteRune(ch)
	}
	return b.String()
}

// ---------------------------------------------------------------- handlers

type server struct {
	cfg     config
	store   *store
	pairLim *limiter
	mintLim *limiter
	client  *http.Client
}

func (s *server) handleRegister(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Code  string `json:"code"`
		URL   string `json:"url"`
		Key   string `json:"key"`
		Claim string `json:"claim"`
	}
	if err := decode(r, &body); err != nil {
		fail(w, 400, "bad request")
		return
	}
	code := normalizeCode(body.Code)
	if len(code) != 8 {
		fail(w, 400, "a code is eight characters")
		return
	}
	if !strings.HasPrefix(body.URL, "https://") {
		fail(w, 400, "an internet address must be https")
		return
	}
	if len(body.Key) < 16 || body.Claim == "" {
		fail(w, 400, "the key and its claim are both needed")
		return
	}

	ip := clientIP(r)
	s.store.mu.Lock()
	defer s.store.mu.Unlock()
	s.store.expire()

	// A code belongs to one bridge at a time. An entry that is still alive
	// cannot be taken over by anybody else, which is what stops a code from
	// being hijacked while its bridge is running.
	if existing, ok := s.store.st.Bridges[code]; ok && existing.Expires.After(time.Now().UTC()) {
		if subtle.ConstantTimeCompare([]byte(existing.Claim), []byte(hashClaim(body.Claim))) != 1 {
			fail(w, 409, "that code is in use")
			return
		}
	}

	ttl := time.Duration(s.cfg.PairTTLMinutes) * time.Minute
	s.store.st.Bridges[code] = bridge{
		Code:    code,
		URL:     strings.TrimRight(body.URL, "/"),
		Key:     body.Key,
		IP:      ip,
		Claim:   hashClaim(body.Claim),
		Expires: time.Now().UTC().Add(ttl),
		Seen:    time.Now().UTC(),
	}
	s.store.save()
	log.Printf("register %s at %s from %s", code, body.URL, ip)
	writeJSON(w, 200, map[string]any{"ok": true, "ttlSeconds": int(ttl.Seconds())})
}

func (s *server) handleBeat(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Code  string `json:"code"`
		Claim string `json:"claim"`
	}
	if err := decode(r, &body); err != nil {
		fail(w, 400, "bad request")
		return
	}
	code := normalizeCode(body.Code)

	s.store.mu.Lock()
	defer s.store.mu.Unlock()
	entry, ok := s.store.st.Bridges[code]
	if !ok {
		fail(w, 404, "no such bridge")
		return
	}
	if subtle.ConstantTimeCompare([]byte(entry.Claim), []byte(hashClaim(body.Claim))) != 1 {
		fail(w, 403, "not yours")
		return
	}
	ttl := time.Duration(s.cfg.PairTTLMinutes) * time.Minute
	entry.Expires = time.Now().UTC().Add(ttl)
	entry.Seen = time.Now().UTC()
	s.store.st.Bridges[code] = entry
	s.store.save()
	writeJSON(w, 200, map[string]any{"ok": true, "ttlSeconds": int(ttl.Seconds())})
}

func (s *server) handleDrop(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Code  string `json:"code"`
		Claim string `json:"claim"`
	}
	if err := decode(r, &body); err != nil {
		fail(w, 400, "bad request")
		return
	}
	code := normalizeCode(body.Code)

	s.store.mu.Lock()
	defer s.store.mu.Unlock()
	entry, ok := s.store.st.Bridges[code]
	if ok && subtle.ConstantTimeCompare([]byte(entry.Claim), []byte(hashClaim(body.Claim))) == 1 {
		delete(s.store.st.Bridges, code)
		s.store.save()
	}
	writeJSON(w, 200, map[string]any{"ok": true})
}

// handlePair is what the phone calls with eight characters typed in.
func (s *server) handlePair(w http.ResponseWriter, r *http.Request) {
	ip := clientIP(r)
	if !s.pairLim.allow(ip) {
		fail(w, 429, "too many attempts - wait a few minutes and try again")
		return
	}
	var body struct {
		Code string `json:"code"`
	}
	if err := decode(r, &body); err != nil {
		fail(w, 400, "bad request")
		return
	}
	code := normalizeCode(body.Code)

	s.store.mu.Lock()
	entry, ok := s.store.st.Bridges[code]
	if ok && entry.Expires.Before(time.Now().UTC()) {
		delete(s.store.st.Bridges, code)
		ok = false
	}
	s.store.mu.Unlock()

	if !ok {
		// The same answer for "never existed" and "not running now", so the
		// reply cannot be used to find out which codes exist.
		fail(w, 404, "no bridge is running with that code")
		return
	}
	writeJSON(w, 200, map[string]any{
		"url":      entry.URL,
		"key":      entry.Key,
		"expires":  entry.Expires,
		"protocol": 1,
	})
}

// handleTunnel creates a fixed address for a new install, so a bridge that
// restarts is still at the address its code pointed at.
func (s *server) handleTunnel(w http.ResponseWriter, r *http.Request) {
	ip := clientIP(r)
	if !s.mintLim.allow(ip) {
		fail(w, 429, "too many new bridges from this address today")
		return
	}
	var body struct {
		Slug string `json:"slug"`
		Port int    `json:"port"`
	}
	_ = decode(r, &body)
	// The tunnel forwards to the bridge's own port on the machine it runs on.
	// 8765 is the bridge's default; anything else is taken as given.
	origin := body.Port
	if origin < 1024 || origin > 65535 {
		origin = 8765
	}

	cf := s.cfg.Cloudflare
	if cf.Token == "" || cf.Account == "" || cf.Zone == "" || cf.Prefix == "" {
		fail(w, 503, "this server has no Cloudflare credentials yet")
		return
	}

	slug := sanitizeSlug(body.Slug)
	if slug == "" {
		slug = randomHex(5)
	}
	hostname := slug + "." + cf.Prefix

	id, token, err := s.makeCloudflareTunnel(r, slug, hostname, origin)
	if err != nil {
		log.Printf("tunnel/new: %v", err)
		fail(w, 502, "Cloudflare refused: "+err.Error())
		return
	}
	if err := s.pointDNS(r, hostname, id); err != nil {
		log.Printf("tunnel/new dns: %v", err)
		fail(w, 502, "the address could not be made: "+err.Error())
		return
	}

	rotate := randomHex(16)
	s.store.mu.Lock()
	s.store.st.Tunnels[slug] = tunnel{
		Slug: slug, Hostname: "https://" + hostname, TunnelID: id,
		Token: token, IP: ip, Created: time.Now().UTC(), RotateKey: rotate,
	}
	s.store.save()
	s.store.mu.Unlock()

	log.Printf("tunnel/new %s for %s", hostname, ip)
	writeJSON(w, 200, map[string]any{
		"hostname":  "https://" + hostname,
		"token":     token,
		"rotateKey": rotate,
	})
}

func sanitizeSlug(in string) string {
	out := strings.Builder{}
	for _, ch := range strings.ToLower(in) {
		if (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') {
			out.WriteRune(ch)
		}
	}
	s := out.String()
	if len(s) > 40 {
		s = s[:40]
	}
	return s
}

func (s *server) handleHealth(w http.ResponseWriter, r *http.Request) {
	s.store.mu.Lock()
	n := len(s.store.st.Bridges)
	m := len(s.store.st.Tunnels)
	s.store.mu.Unlock()
	writeJSON(w, 200, map[string]any{
		"ok": true, "version": version, "bridges": n, "tunnels": m,
		"cloudflare": s.cfg.Cloudflare.Token != "",
	})
}

func main() {
	cfgPath := "/autosongs/paird/config.json"
	if p := os.Getenv("PAIRD_CONFIG"); p != "" {
		cfgPath = p
	}
	cfg, err := loadConfig(cfgPath)
	if err != nil {
		log.Fatalf("config: %v", err)
	}
	if v := os.Getenv("PAIRD_LISTEN"); v != "" {
		cfg.Listen = v
	}

	srv := &server{
		cfg:     cfg,
		store:   newStore(cfg.State),
		pairLim: newLimiter(cfg.PairPerTenMin),
		mintLim: newLimiter(cfg.MaxTunnelsPerIP),
		client:  &http.Client{Timeout: 20 * time.Second},
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/api/paird/bridge/register", srv.handleRegister)
	mux.HandleFunc("/api/paird/bridge/beat", srv.handleBeat)
	mux.HandleFunc("/api/paird/bridge/drop", srv.handleDrop)
	mux.HandleFunc("/api/paird/pair", srv.handlePair)
	mux.HandleFunc("/api/paird/tunnel/new", srv.handleTunnel)
	mux.HandleFunc("/api/paird/healthz", srv.handleHealth)
	// The paths above are also served without the prefix, so a reverse proxy
	// that strips it still works.
	mux.HandleFunc("/bridge/register", srv.handleRegister)
	mux.HandleFunc("/bridge/beat", srv.handleBeat)
	mux.HandleFunc("/bridge/drop", srv.handleDrop)
	mux.HandleFunc("/pair", srv.handlePair)
	mux.HandleFunc("/tunnel/new", srv.handleTunnel)
	mux.HandleFunc("/healthz", srv.handleHealth)

	// Expiry is swept on its own, so a bridge that is killed rather than
	// stopped stops being reachable instead of lingering.
	go func() {
		for range time.Tick(time.Minute) {
			srv.store.mu.Lock()
			srv.store.expire()
			srv.store.save()
			srv.store.mu.Unlock()
		}
	}()

	log.Printf("paird %s listening on %s (%d bridges, %d tunnels)", version, cfg.Listen, len(srv.store.st.Bridges), len(srv.store.st.Tunnels))
	httpSrv := &http.Server{
		Addr:              cfg.Listen,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}
	if err := httpSrv.ListenAndServe(); err != nil {
		log.Fatalf("listen: %v", err)
	}
}

// ---------------------------------------------------------------- cloudflare

func (s *server) cfDo(r *http.Request, method, path string, body any, into any) error {
	var reader io.Reader
	if body != nil {
		raw, err := json.Marshal(body)
		if err != nil {
			return err
		}
		reader = strings.NewReader(string(raw))
	}
	req, err := http.NewRequestWithContext(r.Context(), method,
		"https://api.cloudflare.com/client/v4"+path, reader)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+s.cfg.Cloudflare.Token)
	req.Header.Set("Content-Type", "application/json")

	resp, err := s.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 256*1024))

	var envelope struct {
		Success bool              `json:"success"`
		Errors  []struct{ Message string `json:"message"` } `json:"errors"`
		Result  json.RawMessage   `json:"result"`
	}
	if err := json.Unmarshal(raw, &envelope); err != nil {
		return fmt.Errorf("unexpected reply from Cloudflare (%d)", resp.StatusCode)
	}
	if !envelope.Success || resp.StatusCode >= 300 {
		msg := "refused"
		if len(envelope.Errors) > 0 {
			msg = envelope.Errors[0].Message
		}
		return errors.New(msg)
	}
	if into != nil {
		return json.Unmarshal(envelope.Result, into)
	}
	return nil
}

func (s *server) makeCloudflareTunnel(r *http.Request, slug, hostname string, origin int) (string, string, error) {
	var made struct {
		ID    string `json:"id"`
		Token string `json:"token"`
	}
	err := s.cfDo(r, "POST", "/accounts/"+s.cfg.Cloudflare.Account+"/cfd_tunnel", map[string]any{
		"name":       "autosongs-" + slug,
		"config_src": "cloudflare",
	}, &made)
	if err != nil {
		return "", "", err
	}
	if made.ID == "" {
		return "", "", errors.New("Cloudflare made no tunnel")
	}

	// What the tunnel forwards. The bridge listens on 8765 on the machine it
	// runs on; anything else is a field on the origin, so it is passed through.
	var cfg struct {
		Config struct {
			Ingress []map[string]any `json:"ingress"`
		} `json:"config"`
	}
	cfg.Config.Ingress = []map[string]any{
		{"hostname": hostname, "service": fmt.Sprintf("http://127.0.0.1:%d", origin)},
		{"service": "http_status:404"},
	}
	if err := s.cfDo(r, "PUT", "/accounts/"+s.cfg.Cloudflare.Account+"/cfd_tunnel/"+made.ID+"/configurations", cfg, nil); err != nil {
		return "", "", err
	}

	token := made.Token
	if token == "" {
		var tok struct {
			Token string `json:"token"`
		}
		if err := s.cfDo(r, "GET", "/accounts/"+s.cfg.Cloudflare.Account+"/cfd_tunnel/"+made.ID+"/token", nil, &tok); err != nil {
			return "", "", err
		}
		token = tok.Token
	}
	if token == "" {
		return "", "", errors.New("Cloudflare made no tunnel token")
	}
	return made.ID, token, nil
}

func (s *server) pointDNS(r *http.Request, hostname, tunnelID string) error {
	record := map[string]any{
		"type":    "CNAME",
		"name":    hostname,
		"content": tunnelID + ".cfargotunnel.com",
		"proxied": true,
		"ttl":     1,
	}
	var out map[string]any
	err := s.cfDo(r, "POST", "/zones/"+s.cfg.Cloudflare.Zone+"/dns_records", record, &out)
	if err == nil {
		return nil
	}
	// The record may already exist from an earlier start of the same install;
	// then it is edited rather than made again.
	var found []struct {
		ID string `json:"id"`
	}
	if listErr := s.cfDo(r, "GET", "/zones/"+s.cfg.Cloudflare.Zone+"/dns_records?type=CNAME&name="+hostname, nil, &found); listErr != nil || len(found) == 0 {
		return err
	}
	return s.cfDo(r, "PATCH", "/zones/"+s.cfg.Cloudflare.Zone+"/dns_records/"+found[0].ID, record, nil)
}
