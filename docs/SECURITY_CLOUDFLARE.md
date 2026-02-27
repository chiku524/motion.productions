# Cloudflare Security — Dashboard Checklist

Use this to resolve Cloudflare Security insights for **motion.productions**.

---

## 1. Critical — Managed Rules (WAF)

**Risk:** No WAF protection against SQLi, XSS, and known CVEs.

**Fix:**

1. Log in to [Cloudflare Dashboard](https://dash.cloudflare.com)
2. Select the zone **motion.productions**
3. Go to **Security** → **WAF**
4. Under **Managed rules**, click **Deploy** or **Enable**
5. Enable at least:
   - **Cloudflare Managed Ruleset** (OWASP Core Ruleset, SQLi, XSS, etc.)
   - Optionally: **Cloudflare OWASP Core Ruleset** if listed separately

**Note:** Some rules may require Workers Paid or a higher plan. Enable what your plan allows.

---

## 2. Moderate — Block AI Bots

**Risk:** AI crawlers can freely use your content for training.

**Fix:**

1. **Security** → **Bots**
2. Find the **Block AI bots** toggle
3. Turn it **On**

This blocks known AI crawlers (e.g., GPTBot, ClaudeBot, others). If you want search engines but not AI crawlers, this is usually safe.

---

## 3. Moderate — Bot Settings from Previous Plan

**Risk:** Old bot rules from a previous plan may block or challenge legitimate traffic.

**Fix:**

1. **Security** → **Bots**
2. Review all enabled settings
3. If you recently changed plans (e.g., Free → Workers Paid):
   - Turn off any options marked as "from previous plan" or no longer supported
   - Keep **Bot Fight Mode** or **Super Bot Fight Mode** only if they match your current plan
   - Re-test the site and API from a normal browser after changes

**Tip:** Use **Security** → **Events** to check for false positives (legitimate users blocked).

---

## 4. Low — Security.txt

**Status:** Implemented in the Worker.

The Worker serves `/.well-known/security.txt` and `/security.txt` with:

- **Contact:** `mailto:security@motion.productions`
- **Expires:** 2026-12-31 (update before expiry)

To change the contact, edit `cloudflare/src/index.ts` (search for `security.txt`) and redeploy.

---

## Verification

| Item              | How to verify                                    |
|-------------------|--------------------------------------------------|
| Managed Rules     | Security → WAF → Managed rules show "Enabled"    |
| Block AI bots     | Security → Bots → Block AI bots = On             |
| Bot settings      | No warnings about unsupported/previous-plan rules|
| Security.txt      | `curl https://motion.productions/.well-known/security.txt` |
