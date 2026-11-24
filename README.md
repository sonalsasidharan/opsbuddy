# OpsBuddy

A Streamlit dashboard that explains failing Kubernetes pods to stakeholders, developers and DevOps.

- Lists every pod in a namespace with a health dot.
- Click a pod to see what went wrong, the error log lines, warning events, and which commit probably caused it (looked up on GitHub from the image tag).
- **Search logs**: keyword, regex, level and time-window search straight from Kubernetes. No LLM involved.
- **Analyze with Claude**: a root-cause analysis and a follow-up chat. You preview exactly what will be sent and approve it first.
- **Ask OpsBuddy** tab: quick questions about pod status, logs, events and commits. It never sends data to Claude.

Everything below was run on **Windows 11 with Docker Desktop and a local kind cluster**. macOS and Linux steps are given where they differ, but those were not tested.

---

## For Claude Code (read this first)

If you are Claude Code and a teammate asked you to set this app up, follow the numbered steps in this file in order. Rules:

1. Run each step, check its output, and only then go to the next one. Stop and tell the user if a step fails.
2. Steps 1 and 2 install software (WSL, Docker Desktop) and need an administrator prompt and possibly a reboot. Ask the user before running them. If the tools already exist, skip them.
3. Do not create or ask for an Anthropic API key. Step 6 explains that this app uses the user's existing Claude Code login.
4. Do not put real secrets, tokens or customer logs into anything you commit.
5. `repos.json` ships with a demo mapping. Ask the user for their real repositories before replacing it (step 8).

---

## What you need

| Tool | Tested version | Used for |
|---|---|---|
| Python | 3.12 | the app |
| Docker Desktop | 29.x (WSL2 backend on Windows) | runs the kind cluster |
| kind | any recent | local Kubernetes cluster |
| kubectl | 1.3x | talks to the cluster |
| Claude Code CLI (`claude`) | 2.1.x | the LLM, through your own login |
| Git | any | clone the repo |

You do not need an Anthropic API key. See step 6.

---

## Step 1. Install Docker Desktop (Windows)

1. Open PowerShell **as administrator** and run `wsl --install`. Reboot if it asks you to. If it says the WSL installation is corrupted, accept the repair prompt and rerun it.
2. Install Docker Desktop from https://www.docker.com/products/docker-desktop/ and start it. Wait until it says it is running.
3. Check:

```powershell
wsl --status
docker --version
docker ps
```

`docker ps` must print a table (even an empty one) and not an error.

macOS or Linux: install Docker Desktop or Docker Engine and skip the WSL part.

## Step 2. Install kind and kubectl

Windows (winget):

```powershell
winget install -e --id Kubernetes.kind
winget install -e --id Kubernetes.kubectl
```

Close and reopen the terminal afterwards so the new `PATH` is picked up. On macOS use `brew install kind kubectl`. Check:

```powershell
kind version
kubectl version --client
```

If `kind` is not found, `winget` installed it but your terminal has an old `PATH`. Open a new terminal.

## Step 3. Get the code and set up Python

```powershell
git clone <this-repo-url> opsbuddy
cd opsbuddy
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

macOS or Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

If `pip.exe` is blocked by a company policy, `python -m pip` (as above) works around it.

Sanity check: this must print `FAILURES: 0`.

```powershell
.venv\Scripts\python.exe -X utf8 test_masking.py
```

## Step 4. Create the cluster and the sample pods

```powershell
kind create cluster --name opsbuddy
kubectl config use-context kind-opsbuddy
kubectl apply -f sample-pods.yaml
kubectl get pods -n demo-apps
```

`sample-pods.yaml` creates the namespace `demo-apps` with three pods:

| Pod | What it does |
|---|---|
| `healthy-api-7d9f` | nginx, stays healthy |
| `payment-service-5c8b` | crash-loops with a database connection error and fake secrets (to test masking) |
| `promo-service-3a1d` | `ImagePullBackOff` (bad image) |

After a minute `payment-service` shows `Error` or `CrashLoopBackOff`, and `promo-service` shows `ImagePullBackOff`. That is the point of the demo.

### Step 4b. Make the payment pod's image pullable (needed once)

The payment pod uses the image `localhost:5001/payment-service:7fd1a60`. The tag is a commit SHA, which is how OpsBuddy finds the commit. kind nodes can't pull from your machine's `localhost`, so we run a tiny local registry and point the kind node at it. (`kind load docker-image` failed on Docker 29 with a digest error, which is why we use a registry.)

```powershell
docker run -d --restart=always -p 127.0.0.1:5001:5000 --network kind --name kind-registry registry:2
docker pull busybox:1.36
docker tag busybox:1.36 localhost:5001/payment-service:7fd1a60
docker push localhost:5001/payment-service:7fd1a60
docker exec opsbuddy-control-plane mkdir -p /etc/containerd/certs.d/localhost:5001
```

Create the node's registry config. In PowerShell, quoting breaks if you write it inline, so write a file and copy it in:

```powershell
$f = "$env:TEMP\hosts.toml"
[IO.File]::WriteAllText($f, "[host.`"http://kind-registry:5000`"]`n")
docker cp $f "opsbuddy-control-plane:/etc/containerd/certs.d/localhost:5001/hosts.toml"
docker exec opsbuddy-control-plane cat /etc/containerd/certs.d/localhost:5001/hosts.toml
```

On macOS or Linux you can use `docker exec opsbuddy-control-plane sh -c 'printf "[host.\"http://kind-registry:5000\"]\n" > /etc/containerd/certs.d/localhost:5001/hosts.toml'`.

Then restart the payment pod so it pulls again:

```powershell
kubectl delete pod payment-service-5c8b -n demo-apps
kubectl apply -f sample-pods.yaml
kubectl get pods -n demo-apps
```

The payment pod should now reach `Error` / `CrashLoopBackOff` (it started, then crashed on purpose) instead of `ImagePullBackOff`. If it stays at `ImagePullBackOff`, re-check the registry container (`docker ps`) and the `hosts.toml` file.

You can skip 4b and still use the app. The payment pod will then show an image-pull error and the commit lookup is simply less interesting.

## Step 5. (Recommended) Use a read-only cluster identity

By default the app uses your normal kubeconfig, which on kind is cluster admin. OpsBuddy only reads, so give it a read-only identity. `rbac.yaml` allows get/list on pods, events and namespaces and get on pod logs, and nothing else (no secrets, no exec, no writes).

```powershell
powershell -ExecutionPolicy Bypass -File .\make-readonly-kubeconfig.ps1
```

This writes `secrets\opsbuddy-readonly.kubeconfig` (git-ignored) with a **24-hour token**. Rerun the script to refresh it. Verify it:

```powershell
kubectl --kubeconfig secrets\opsbuddy-readonly.kubeconfig auth can-i list pods -A      # yes
kubectl --kubeconfig secrets\opsbuddy-readonly.kubeconfig auth can-i delete pods -A     # no
```

The script is PowerShell. On macOS or Linux you would need to do the same steps with `kubectl` by hand (apply `rbac.yaml`, `kubectl create token opsbuddy-reader -n opsbuddy --duration=24h`, and build a kubeconfig around it). That was not tested.

## Step 6. Add Claude (the LLM)

OpsBuddy calls Claude in one of two ways, chosen automatically in `llm.py`:

| Backend | When it is used | Needs |
|---|---|---|
| **Claude Code** (what we used) | `claude` is on your `PATH` and logged in | your normal Claude login. No API key and no extra payment. It counts against your own plan's usage. |
| Anthropic API | the environment variable `ANTHROPIC_API_KEY` is set | an API key with billing. **Not tested live**, so expect to debug it. |

If `ANTHROPIC_API_KEY` is set, the API wins. Unset it to use Claude Code.

### How the Claude Code backend works

OpsBuddy runs the CLI in non-interactive print mode, with the prompt on stdin, in a throwaway temp directory:

```
claude -p --tools "" --strict-mcp-config --disable-slash-commands --no-session-persistence --output-format text --system-prompt "<instructions>"
```

- `--tools ""` gives Claude **no tools**. It can't run commands or read files, even if a log line tries to tell it to (prompt injection).
- `--strict-mcp-config`, `--disable-slash-commands` and `--no-session-persistence` keep out connectors, skills and saved sessions.
- A temp working directory stops it picking up this project's files or any `CLAUDE.md`.

So your teammate's own Claude Code install and login is all that is needed.

### Set it up on your machine

1. Install Claude Code using the install instructions in Anthropic's official Claude Code documentation (look up the current command for your OS; it isn't pinned here because it changes).
2. Run `claude` once in a terminal and log in with your account.
3. Check it works from a plain terminal:

```powershell
claude --version
"Say hello in five words" | claude -p --tools ""
```

You should get a short reply. If you get a login prompt or an error, fix that first. The app shows which backend is active in its sidebar.

### What gets sent to Claude

Only when you click **Approve and send** (or send a follow-up). Before that, OpsBuddy shows you the exact text: pod state, the error lines, warning events, and the suspect commit's author and message. Secrets are masked first (`masking.py`: URL passwords, cloud keys, tokens, JWTs, `password=` style values, emails, card numbers, long opaque strings). Masking is a safety net, not a guarantee. **Read the preview.** The data goes to Anthropic through your login, so check your company's policy on sending logs to an LLM before using real production logs.

## Step 7. Run the app

```powershell
$env:OPSBUDDY_KUBECONFIG = "$PWD\secrets\opsbuddy-readonly.kubeconfig"   # skip this line to use your normal kubeconfig
.venv\Scripts\python.exe -m streamlit run app.py
```

Open http://localhost:8501. The server listens on `127.0.0.1` only (set in `.streamlit/config.toml`), because the app has no login of its own. Don't change that to expose it on a network.

`OPSBUDDY_KUBECONFIG` only lasts for that terminal window. Set it again in any new window.

### Try it

1. Pick **demo-apps** in the sidebar. You should see three pods with green or red dots.
2. Click `payment-service-5c8b`. You should see the cause, the error lines (passwords and tokens shown as `***REDACTED***`), and the commit card.
3. Under **Search logs**, try a keyword such as `connection`, a level filter, or a time window.
4. Click **Analyze with Claude**, read the preview, then **Approve and send**. Ask a follow-up in the box underneath.
5. Open the **Ask OpsBuddy** tab and ask "which pods are failing?".

## Step 8. Point it at your real repos (commit lookup)

The "Who caused it" card needs two things: the image tag ends in a commit SHA (7 to 40 hex characters, for example `myapp:7fd1a60`), and OpsBuddy knows which GitHub repo the pod belongs to. It looks for the repo in this order:

1. `repos.json` in the project root, a map of pod-name prefix to `owner/repo`.
2. The `OPSBUDDY_REPOS` environment variable, the same JSON.
3. An image path like `ghcr.io/owner/repo:sha`.

The shipped `repos.json` maps `payment-service` to `octocat/Hello-World`, a **public demo repo**. Replace it with your own:

```json
{ "payment-service": "your-org/payment-service" }
```

Save it as UTF-8. (A BOM is tolerated, but plain UTF-8 is safest.) For private repos, or to avoid GitHub's anonymous rate limit, set a token with read access to repository contents:

```powershell
$env:GITHUB_TOKEN = "<your token>"
```

Never commit a token. Results are cached for 5 minutes.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `kind` or `kubectl` not found | Open a new terminal so `PATH` refreshes. |
| `docker ps` fails | Start Docker Desktop and wait for it to finish starting. |
| `REGDB_E_CLASSNOTREG` from WSL | Run `wsl --install` in an administrator PowerShell, accept the prompts, reboot. |
| Dashboard shows no pods or a connection error | Check `kubectl get pods -n demo-apps`. The read-only token may have expired (24h): rerun `make-readonly-kubeconfig.ps1` and restart the app. |
| Payment pod stuck on `ImagePullBackOff` | Redo step 4b. |
| Emoji or accent `UnicodeEncodeError` in a script | Run Python with `-X utf8`. |
| Sidebar says "Claude analysis is off", or Analyze shows an error | Run `claude -p "hi"` in a terminal. Fix login first. If `ANTHROPIC_API_KEY` is set to something invalid, unset it. |
| Analysis is slow | It shells out to the CLI. The timeout is 240 seconds. |
| Commit card says "no repo" | Add the pod to `repos.json` (step 8). |
| Commit card says "rate limit" or "not found" | Set `GITHUB_TOKEN`, or check the repo name and that the SHA exists in it. |
| Search logs says there are no logs for the previous run | Normal for crash-looping pods. It falls back to the current container. |
| Masked output shows odd `REDACTED` on harmless IDs | The long-token rule also hides pod UIDs and container IDs. Harmless. |

## Known limits

- Masking can miss secrets in formats it doesn't know. The preview is the real check.
- Prompt injection is reduced (Claude has no tools, output isn't rendered as HTML) but not eliminated. Check any command Claude suggests before running it.
- The app has no login and no audit log of what was sent to Claude.
- Log search reads the latest 5,000 lines of each pod's default container, and only what Kubernetes still holds. For older history you need a log store such as Loki or Elasticsearch.
- The Anthropic API backend has not been exercised live.
- Tested on Windows 11 only. The UI was verified with Streamlit's test harness, not visually in every browser.

## Files

| File | Purpose |
|---|---|
| `app.py` | the Streamlit app: pod list, details, log search, chat |
| `llm.py` | Claude backends, prompts, follow-up chat |
| `masking.py`, `test_masking.py` | secret masking and its tests |
| `gitinfo.py` | commit lookup via the GitHub API |
| `theme.py`, `.streamlit/config.toml` | Konnekt Noir styling and server settings |
| `sample-pods.yaml` | demo namespace and pods |
| `rbac.yaml`, `make-readonly-kubeconfig.ps1` | read-only cluster identity |
| `repos.json` | pod-name prefix to GitHub repo map (demo values) |
