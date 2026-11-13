# Class Clown Ranking

At some point our friend group had a slightly toxic idea: what if we actually tracked how
funny each of us is? Not vaguely, with "you had a good one today", but properly, with a
score, a ranking and a graph that shows exactly when someone stopped being funny.

So we built it. Every day or week, everyone in the group gives every other member an
upvote or a downvote. Each person ends up with a humor score from 0 to 10, a place in the
ranking and a history graph. Groups can make voting anonymous, so nobody finds out who
downvoted them. Please use this responsibly, or at least have fun with it.

The app's interface is in German (the internal name is *Spaßvogel-Ranking*).

## Try the demo

You need Python 3.12 or newer. The demo doesn't need a `.env` file, a mail server or any
accounts.

```bash
git clone https://github.com/noahbridgeman/class-clown-ranking.git
cd class-clown-ranking
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

python scripts/demo.py           # generates nine weeks of demo history in instance/demo.db
python scripts/share_demo.py     # serves it at http://127.0.0.1:5050
```

Open <http://127.0.0.1:5050>. You're logged in as Jonas automatically. He's in two
groups: a flat share that votes weekly, and an office group that votes daily and
anonymously. The other members have already voted in the current period, and your own
votes are still open. A new period is processed every minute, so the scores move while
you watch.

Run `python scripts/demo.py --force` to reset the demo data.

### Sharing the demo with friends

To give friends a public link, keep `share_demo.py` running and start a tunnel in a second
terminal, for example with [ngrok](https://ngrok.com):

```bash
ngrok http 127.0.0.1:5050
```

Everyone who opens the link is Jonas, and everyone shares the same demo database. Only
expose the demo this way, never a real instance.

### The demo with the regular login

If you want to try the real login flow instead (magic links, printed to the terminal
rather than sent):

```bash
cp .env.example .env             # sets APP_ENV=development
python scripts/demo.py --force
DATABASE_URL=sqlite:///demo.db flask --app app run --debug
```

Log in at <http://127.0.0.1:5000> as `jonas@example.org` (or `felix@`, `lena@`,
`mara@` … `example.org`). The login link shows up in the server terminal. To advance
periods, run `DATABASE_URL=sqlite:///demo.db flask --app app tick`.

## How the score works

Each member has an internal rating that starts at 0, which is a score of 5.0. At the end of
each period, the votes they received move the rating up or down. Older rating decays
slowly, so nobody can coast on one legendary week forever. The score is the rating mapped
onto 0 to 10. A finished period's results are stored and never recalculated.

`python scripts/simulate.py --k 0.5 --d 0.95` shows how the score curves behave for
different parameters.

## Stack

Flask, Jinja2 and HTMX, SQLAlchemy with SQLite, ECharts for the graph, and a PWA with web
push. The period update is the idempotent CLI command `flask --app app tick`, meant to be
run every minute by cron or a systemd timer.

## Development

```bash
pip install -e ".[dev]"
cp .env.example .env
flask --app app db upgrade
flask --app app run --debug
pytest
ruff check . && ruff format --check .
```

The requirements, plan and design (in German) are in `docs/`.

## License

MIT, see `LICENSE`. The bundled fonts are under the SIL Open Font License, see
`app/static/fonts/OFL-*.txt`.
