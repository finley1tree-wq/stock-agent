# Making the agent fire on its own

The agent itself is fine. The only fragile part is **what wakes it up**.

## What happened on 2026-09-08

GitHub's scheduler never fired for this repo. Not once. Proof: a throwaway workflow set to run
every 5 minutes produced zero runs across four slots, and `event=schedule` has a lifetime total of
zero runs. Manual dispatch works every single time, Actions is enabled, billing is clean, GitHub
Actions was reporting "operational". This is almost certainly a brand-new repository whose
schedules have not activated yet.

The result: the market opened at 9:30 ET and the agent did not check in until 11:17 ET, after a
manual dispatch. It then traded correctly.

**The watchdog does not save you here.** `watchdog.yml` is itself on a cron, so when GitHub's
scheduler is asleep the watchdog is asleep too. Real insurance has to come from outside GitHub.

## Layer 1 — GitHub cron (already set up, free)

`agent.yml` at `:02` and `:32`, `watchdog.yml` at `:17` and `:47`. Leave these alone. They will
very likely start working on their own within a day, and once they do they carry the whole load.

## Layer 2 — an outside alarm clock (5 minutes, do this once)

This is what makes it actually reliable, because it does not share a single line of code or
infrastructure with layer 1.

**Step 1 — make a token.** Open
<https://github.com/settings/personal-access-tokens/new>

- Token name: `stock-agent trigger`
- Expiration: 1 year (put a reminder to renew)
- Repository access: **Only select repositories** -> `stock-agent`
- Permissions -> Repository permissions -> **Actions: Read and write**
- Generate, then copy the token. It is shown once.

This token can start workflows in this one repo and nothing else. It cannot read your other repos
or touch your account.

**Step 2 — make the alarm.** Open <https://console.cron-job.org/signup>, create a free account,
then "Create cronjob":

| Field | Value |
|---|---|
| Title | stock-agent |
| URL | `https://api.github.com/repos/finley1tree-wq/stock-agent/actions/workflows/agent.yml/dispatches` |
| Schedule | Every 30 minutes, minutes `2` and `32`, hours `13`–`21`, Mon–Fri, timezone **UTC** |
| Request method (Advanced) | `POST` |
| Request body (Advanced) | `{"ref":"main"}` |

Headers (Advanced -> Headers):

```
Authorization: Bearer PASTE_YOUR_TOKEN_HERE
Accept: application/vnd.github+json
Content-Type: application/json
X-GitHub-Api-Version: 2022-11-28
```

Save and hit "Test run". A success looks like HTTP **204** with an empty body, and a new run
appears at <https://github.com/finley1tree-wq/stock-agent/actions>.

That is it. From then on two independent systems are trying to wake the agent every 30 minutes,
and the agent exits in seconds whenever the market is closed, so extra pings cost nothing.

## Why not just let a GitHub job sit and wait?

Because a runner that sleeps through the trading day bills for the whole 6.5 hours: about 390
minutes a day, roughly 8,200 a month, against a 2,000-minute free allowance on a private repo. It
only becomes free if the repository is made public. That is a real option, it just means the code
and the pretend portfolio become visible to anyone. The API keys stay secret either way, because
they live in Actions secrets and never in the repository.

## Checking it is alive

- Dashboard header at <https://stock-agent-swart.vercel.app> shows "agent data" and a timestamp,
  and turns amber if nothing has checked in for 45 minutes while the market is open.
- `gh run list -R finley1tree-wq/stock-agent -L 5`
- Actions -> **doctor** -> Run workflow, to test the keys GitHub holds without trading.
