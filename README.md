# BrightEdge Engineering Developer Assignment — Submission

A URL → metadata + topics service, plus a design and PoC plan to scale it to
billions of URLs per month.

## Repository layout

```
submission/
├── app/                      # Part 1 — the working service
│   ├── fetcher.py            #   HTTP fetch (HTTP/2 + retries + UA shaping)
│   ├── robots.py             #   robots.txt check with 6-hour cache
│   ├── extractor.py          #   HTML → metadata (OG, JSON-LD, body)
│   ├── classifier.py         #   page_category + ranked topics
│   └── main.py               #   FastAPI app, GET /classify?url=…
├── tests/
│   ├── smoke.py              # Live integration test (hits the 3 assignment URLs)
│   ├── fixtures.py           # HTML fixtures used by the unit tests
│   ├── test_extractor.py     # 5 unit tests
│   ├── test_classifier.py    # 6 unit tests
│   ├── test_partial.py       # 3 unit tests (anti-bot stub detection)
│   └── test_robots.py        # 3 unit tests (robots.txt allow / deny)
├── sample_outputs/           # Captured JSON responses for the 3 URLs
├── docs/
│   ├── 02-design.md          # Part 2 — scale design, schema, SLOs, monitoring
│   └── 03-poc-plan.md        # Part 3 — 3-week PoC plan + release plan
├── deploy/cloud-run.md       # Optional cloud deploy instructions (GCP / AWS)
├── Dockerfile                # Container for local docker run or cloud deploy
├── pyproject.toml            # pytest + ruff config
└── requirements.txt
```

## Quick start — run locally

```bash
cd submission
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Unit tests (fast, hermetic):
.venv/bin/pytest

# CLI smoke test against the 3 URLs from the assignment (hits the network):
.venv/bin/python -m tests.smoke

# HTTP server:
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080
# then in another shell:
curl -s --get 'http://127.0.0.1:8080/classify' \
  --data-urlencode 'url=https://www.cnn.com/2025/09/23/tech/google-study-90-percent-tech-jobs-ai' \
  | python -m json.tool
```

## Quick start — Docker

```bash
docker build -t brightedge-crawler .
docker run -p 8080:8080 brightedge-crawler
```

## Optional: deploy to a public URL

Not required to grade the submission — local `uvicorn` or `docker run` works.
If you want a live URL, the container deploys to Google Cloud Run in one
command (see [deploy/cloud-run.md](deploy/cloud-run.md)):

```bash
gcloud run deploy brightedge-crawler-demo --source . --region us-central1 --allow-unauthenticated
```

## What the service does

`GET /classify?url=<URL>` returns JSON containing:

- **Metadata**: title, description, canonical URL, language, author, publish
  date, OpenGraph + Twitter cards, JSON-LD types, H1/H2 headings, word count,
  body excerpt.
- **Topics**: a ranked list combining structured signals (schema.org
  `category`, `articleSection`, `keywords`, breadcrumbs) and unsupervised
  keyphrase extraction (YAKE) over the title + body.
- **Page category**: a coarse label (`product`, `article`, `video`,
  `recipe`, `event`, `organization`, `website`, `other`) derived primarily
  from schema.org `@type` and OpenGraph `og:type`, with URL-pattern fallbacks.
- **Confidence**: `high` (schema.org + structured topics), `medium`
  (schema.org OR both signal sources), or `low` (URL-pattern fallback only).
- **Partial flag**: `partial: true` with a `partial_reason` when the fetched
  page looks like an anti-bot interstitial (thin content, no JSON-LD, no
  description) — so callers don't treat shallow keywords as a real result.
- **Provenance**: final URL after redirects, HTTP status, fetch time.

The service respects `robots.txt` — a disallowed URL returns HTTP 451 with
a clear message rather than fetching anyway. robots.txt responses are
cached in memory for 6 hours (per the design doc).

## Sample results (full JSON in [sample_outputs/](sample_outputs/))

| URL | Category | Confidence | Partial | Notes |
|---|---|---|---|---|
| CNN article on Google AI study | `article` | `high` | `false` | Full schema.org `NewsArticle` JSON-LD with `articleSection` → structured topics (`business`, `tech`) plus keyphrase topics (`artificial intelligence`, `Google study`, `tech industry workers`). |
| Amazon Cuisinart toaster product | `product` | `low` | `true` | Amazon returned the "Click the button to continue shopping" anti-bot interstitial on this fetch. The pipeline classified by URL pattern (`/dp/`) but flagged `partial: true, partial_reason: "thin_content (word_count=21, no JSON-LD, no description)"` so the caller knows not to trust the topics. On a fetch that gets through, you'd see the real product title and structured product features. |
| REI blog post | (blocked) | — | — | Akamai bot mitigation drops the connection at the TLS layer. Pipeline returns a structured 502 with the error class (`ReadTimeout`). This is the Tier-C case (headless browser + residential IPs) described in [docs/02-design.md §2](docs/02-design.md). |

Together, the three URLs sample three points on the difficulty curve:
fully cooperative (CNN), partially defended (Amazon, sometimes serves real
HTML, sometimes serves a challenge), and hard-defended (REI / Akamai). The
demo handles the first cleanly, flags the second as partial rather than
faking confidence, and surfaces the third as a known limitation that Part 2
addresses with a Tier-C headless-browser fallback.

## How Part 1 maps to the assignment

- **Input**: any URL
- **Output**: HTML metadata (title, description, body, etc.)
- **Plus**: topic list + page category, as the assignment also requested
  (*"classify the page, and return a list of relevant topics"*)
- **Language**: Python
- **Public location** for the code: this GitHub repository. Optional one-command
  Cloud Run deploy in [deploy/cloud-run.md](deploy/cloud-run.md) if a live
  URL is wanted.

## Allowed / not allowed

- Uses 3rd-party libraries for **parsing**: `beautifulsoup4`, `lxml`,
  `trafilatura` for body extraction, `yake` for keyword extraction.
  (Assignment FAQ: *"Can I use external libraries for HTML parsing? Yes."*)
- **Does not** call any 3rd-party service that performs the same end-to-end
  function (e.g. Diffbot, Apify, ScrapingBee).

## AI assistance disclosure

Per the assignment FAQ, here is how AI was used:

- **Claude (Anthropic)** was used as a pair-programming assistant to draft
  the initial Python files (`fetcher.py`, `extractor.py`, `classifier.py`,
  `main.py`, `robots.py`), the unit tests under `tests/`, and the design
  documents in `docs/`. I reviewed every change, ran the tests, and edited
  for correctness and voice.
- During review I caught and fixed a real bug in the AI-drafted
  `extractor._meta()` helper (a `**kwargs` mistake that silently lost meta
  tags) and added a regression test for it; this is in the git history.
- AI was particularly helpful for: enumerating schema.org `@type` values
  for the category map, drafting the protobuf schema in the design doc,
  scaffolding the test fixtures, and a first-pass cost-model table that I
  then refined.
- AI is **not** called at runtime — no LLM is in the request path. The
  service uses only the libraries listed in `requirements.txt`
  (BeautifulSoup, trafilatura, YAKE, FastAPI, httpx).

## Design + PoC documents

- [docs/02-design.md](docs/02-design.md) — full architecture for ingesting
  billions of URLs/month: tiered crawl, dedupe, unified protobuf schema,
  hot KV + analytical lake, SLOs/SLAs, error budgets, cost model,
  reliability, monitoring.
- [docs/03-poc-plan.md](docs/03-poc-plan.md) — 3-week PoC plan with
  workstream breakdown, knowns vs. unknowns vs. risks, evaluation criteria,
  staged release plan, and staffing assumptions.

## What I'd do next (beyond Part 1)

In priority order, if I had another week:

1. Conditional GET (`ETag` / `If-Modified-Since`) — easy 30% cost cut at
   scale, described in §5 of the design doc.
2. Tier-C Playwright fallback wired behind a feature flag, to actually
   handle the REI case end-to-end.
3. Per-host adaptive rate limiter (AIMD on 429/503).
4. A small labeled eval set (~200 URLs) + a `make eval` target that
   measures topic-extraction F1 against it — closes the feedback loop on
   classifier quality changes.
