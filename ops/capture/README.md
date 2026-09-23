# Evidence capture: setup (macOS, once)

```bash
cd ~/Developer/visionguard/ops/capture
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

Then, every time: `source .venv/bin/activate` and follow step 4 of `../RUNBOOK_day1.md`.

Check a capture hasn't been altered:

```bash
python capture.py verify evidence/VG-0001/<folder>
```
