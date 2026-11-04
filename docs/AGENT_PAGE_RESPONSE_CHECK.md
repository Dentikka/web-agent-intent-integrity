# TIME agent-page response check

On 2026-11-04 between 21:51 and 21:53 UTC, five read-only `GET` requests from the same client fetched `https://time.com/`. The two matched pairs used `Accept: text/html` and differed only in `User-Agent`: a Chrome-like browser string or `GPTBot/1.0 (+https://openai.com/gptbot)`. No cookies were supplied. A fifth request used the GPTBot string with `Accept: text/markdown`.

| Request | HTTP status | Content type | Bytes | Labeled Ally ad |
|---|---:|---|---:|---|
| Browser, HTML | 200 | `text/html` | 1,313,863 | Absent |
| Browser, HTML repeat | 200 | `text/html` | 1,313,863 | Absent |
| GPTBot, HTML | 200 | `text/html` | 49,952 | Present |
| GPTBot, HTML repeat | 200 | `text/html` | 49,952 | Present |
| GPTBot, Markdown | 200 | `text/markdown` | 42,373 | Present |

Both HTML responses had the same TIME homepage title. The browser responses contained neither `mobian-agent-ad` nor the Ally sponsorship marker. Both GPTBot HTML responses included a `mobian-agent-ad` element with `data-sponsored=true` and an Ally sponsorship label; their headers included `x-mobian-format: html` and `x-mobian-impression`. The Markdown response also included the labeled ad and `x-mobian-format: md`.

SHA-256 of the response bodies, in table order:

```text
793cff8ab092ef66aba837e7c6f4ebac5b29b45963d0a6cb49f126bf4cd2b63c
793cff8ab092ef66aba837e7c6f4ebac5b29b45963d0a6cb49f126bf4cd2b63c
9b6e60195c3769810bae6d3582e3ab5c5eb1cc0faee624767b645dae9584aeee
4e663f6071ad38b7643a95c0eac88c8f2039b9e25409b65a90bbdcf32a03ee6a
c6f58f044cf2c8b51adbcda2c7ded4391314b96f704dcb6863f8574f78ef5968
```

The check establishes a response difference under these request headers. It does not measure whether an agent reads the ad or changes a decision. Live content and routing can change.
