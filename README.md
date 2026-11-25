# Devops-Konnekt

A Streamlit dashboard that explains failing Kubernetes pods to developers, DevOps and the business team.

When you open it, the first page asks **Who are you?**

- **Developers / DevOps**: every pod, grouped by namespace. Click a pod to see the error log lines, a plain-English "What went wrong", **Who caused it** (the commit behind the running image, looked up on GitHub), a **Search by correlation ID** box, and **Claude's take** (a root-cause analysis and a follow-up chat). You preview exactly what will be sent to Claude and approve it first.
- **Business team**: a simple chat with four suggested questions about which services are working. Detailed or technical questions get a default message pointing the person to the engineering team. This chat never sends data to Claude.

The left panel always shows the cluster you are connected to, the current namespace, overall health, a short how-to, and a Light theme switch.

---

## Quick start (Linux or macOS)

You need Docker, kind, kubectl and Python 3.10 or newer (see "What you need").

```bash
git clone <this-repo-url> devops-konnekt
cd devops-konnekt
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

kind create cluster --name devops-konnekt
kubectl config current-context          # must print: kind-devops-konnekt
kubectl apply -f sample-pods.yaml
kubectl get pods -n demo-apps

.venv/bin/python -m streamlit run app.py
```

Open http://localhost:8501, choose your role, and look at the **Cluster** card in the left panel. It must say `kind-devops-konnekt`. If it shows another name, stop the app: it is reading a different cluster.

The rest of this file explains each step, the optional parts, and Windows.

---

## For Claude Code (read this first)

If you are Claude Code and a teammate asked you to set this app up, follow the numbered steps below in order. Rules:

1. Run each step, check its output, and only then go to the next one. Stop and tell the user if a step fails.
2. Step 1 installs software and may need an administrator prompt and a reboot. Ask the user before running it. If the tools already exist, skip it.
3. Before any `kubectl` command, run `kubectl config current-context` and ask the user to confirm it is the intended cluster.
4. Do not create or ask for an Anthropic API key. Step 5 explains that this app uses the user's existing Claude Code login.
5. Do not put real secrets, tokens or customer logs into anything you commit.
6. `repos.json` ships with a demo mapping. Ask the user for their real repositories before replacing it (step 7).

---

## What you need

| Tool | Version used | Used for |
|---|---|---|
| Python | 3.10 or newer (3.10 and 3.12 have been used) | the app |
| Docker | Docker Desktop on Windows, Docker Engine 28.x on Linux | runs the kind cluster |
| kind | 0.26 on Linux | local Kubernetes cluster |
| kubectl | any recent | talks to the cluster |
| Claude Code CLI (`claude`) | 2.1.x | the LLM, through your own login |
| Git | any | clone the repo |

The Python packages are in `requirements.txt` (the app was run with Streamlit 1.65). You do not need an Anthropic API key. See step 5.

The original setup was run on Windows 11. The current UI was run on Ubuntu Linux (Docker 28, kind 0.26, Python 3.10). macOS was not tested.

---

## Step 1. Install the tools

**Linux:** install Docker Engine, kind and kubectl from their official documentation (the install commands change, so they are not pinned here). Check:

```bash
docker ps
kind version
kubectl version --client
```

`docker ps` must print a table (even an empty one) and not an error.

**macOS:** install Docker Desktop, then `brew install kind kubectl`.

**Windows:**

1. In PowerShell **as administrator**, run `wsl --install` and reboot if asked.
2. Install Docker Desktop from https://www.docker.com/products/docker-desktop/ and wait until it says it is running.
3. Install kind and kubectl, then open a new terminal so `PATH` refreshes:

```powershell
winget install -e --id Kubernetes.kind
winget install -e --id Kubernetes.kubectl
```

## Step 2. Get the code and set up Python

Linux or macOS:

```bash
git clone <this-repo-url> devops-konnekt
cd devops-konnekt
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python test_masking.py        # must print FAILURES: 0
```

Windows:

```powershell
git clone <this-repo-url> devops-konnekt
cd devops-konnekt
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -X utf8 test_masking.py
```

If `pip.exe` is blocked by a company policy, `python -m pip` (as above) works around it.

## Step 3. Create the cluster and the sample pods

```bash
kind create cluster --name devops-konnekt
kubectl config use-context kind-devops-konnekt
kubectl config current-context          # must print kind-devops-konnekt
kubectl apply -f sample-pods.yaml
kubectl get pods -n demo-apps
```

The cluster is `devops-konnekt`, its kubectl context is `kind-devops-konnekt`, and its Docker container is `devops-konnekt-control-plane`.

`sample-pods.yaml` creates the namespace `demo-apps` with four pods:

| Pod | What it does |
|---|---|
| `healthy-api-7d9f` | nginx, stays healthy |
| `payment-service-5c8b` | crash-loops with a database connection error and fake secrets (to test masking) |
| `orders-service-4e2a` | a Python code bug (`KeyError`) that crash-loops. Its logs hold a correlation ID, `3f2a9c1d-0003`, and a made-up committer line. |
| `promo-service-3a1d` | `ImagePullBackOff` (bad image) |

After a minute the failing pods show `CrashLoopBackOff` or `ImagePullBackOff`. That is the point of the demo. `orders-service-4e2a` needs internet access to pull `python:3.12-alpine`.

### Step 3b. Make the payment pod's image pullable (optional)

The payment pod uses the image `localhost:5001/payment-service:7fd1a60`. The tag is a commit ID, which is how Devops-Konnekt finds the commit. kind nodes can't pull from your machine's `localhost`, so run a small local registry and point the kind node at it:

```bash
docker run -d --restart=always -p 127.0.0.1:5001:5000 --network kind --name kind-registry registry:2
docker pull busybox:1.36
docker tag busybox:1.36 localhost:5001/payment-service:7fd1a60
docker push localhost:5001/payment-service:7fd1a60
docker exec devops-konnekt-control-plane mkdir -p /etc/containerd/certs.d/localhost:5001
docker exec devops-konnekt-control-plane sh -c 'printf "[host.\"http://kind-registry:5000\"]\n" > /etc/containerd/certs.d/localhost:5001/hosts.toml'
```

On Windows PowerShell, quoting breaks if you write the config inline, so write a file and copy it in:

```powershell
$f = "$env:TEMP\hosts.toml"
[IO.File]::WriteAllText($f, "[host.`"http://kind-registry:5000`"]`n")
docker cp $f "devops-konnekt-control-plane:/etc/containerd/certs.d/localhost:5001/hosts.toml"
```

Then restart the payment pod so it pulls again:

```bash
kubectl delete pod payment-service-5c8b -n demo-apps
kubectl apply -f sample-pods.yaml
```

The payment pod should now crash (it started, then failed on purpose) instead of showing `ImagePullBackOff`. You can skip this step. The app still works, and the payment pod just shows an image-pull error.

## Step 4. (Recommended) Use a read-only cluster identity

By default the app uses your normal kubeconfig, which on kind is cluster admin. Devops-Konnekt only reads, so give it a read-only identity. `rbac.yaml` allows get and list on pods, events and namespaces, and get on pod logs, and nothing else.

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File .\make-readonly-kubeconfig.ps1
```

This writes `secrets\devops-konnekt-readonly.kubeconfig` (git-ignored) with a **24-hour token**. Rerun the script to refresh it. Verify it:

```powershell
kubectl --kubeconfig secrets\devops-konnekt-readonly.kubeconfig auth can-i list pods -A      # yes
kubectl --kubeconfig secrets\devops-konnekt-readonly.kubeconfig auth can-i delete pods -A     # no
```

On Linux or macOS the script does not run. You would apply `rbac.yaml`, run `kubectl create token devops-konnekt-reader -n devops-konnekt --duration=24h`, and build a kubeconfig around the token by hand. That has not been tested.

## Step 5. Add Claude (the LLM)

Devops-Konnekt calls Claude in one of two ways, chosen automatically in `llm.py`:

| Backend | When it is used | Needs |
|---|---|---|
| **Claude Code** | `claude` is on your `PATH` and logged in | your normal Claude login. No API key. It counts against your own plan's usage. |
| Anthropic API | the environment variable `ANTHROPIC_API_KEY` is set | an API key with billing. **Not tested live**, so expect to debug it. |

If `ANTHROPIC_API_KEY` is set, the API wins. Unset it to use Claude Code.

Set up Claude Code:

1. Install Claude Code using the instructions in Anthropic's official documentation.
2. Run `claude` once in a terminal and log in.
3. Check it works:

```bash
claude --version
echo "Say hello in five words" | claude -p --tools ""
```

### How the Claude Code backend runs

The app runs the CLI in non-interactive mode, with the prompt on stdin, in a temporary directory, with no tools, no connectors, no skills, no saved session and only the project-level settings (so your personal `CLAUDE.md` does not leak into answers). Claude can't run commands or read files, even if a log line tries to tell it to.

### What Claude is asked to do

Claude first decides whether the failure is a **code issue** or a **deployment issue**.
- **Code issue:** "How to fix it" is for the developer: the exception, the file and line from the stack trace if present, the change to make and a test to add. No `kubectl` commands.
- **Deployment issue:** "How to fix it" is for the DevOps team, with the issue and the exact commands or manifest changes.

### What gets sent to Claude

Only when you click **Approve and send** (or send a follow-up). Before that, the app shows the exact text: pod state, the error lines, the last log lines (which include stack trace frames), warning events, and the suspect commit's author and message. Secrets are masked first (`masking.py`: URL passwords, cloud keys, tokens, JWTs, `password=` style values, emails, card numbers, long opaque strings). Masking is a safety net, not a guarantee. **Read the preview.** The data goes to Anthropic through your login, so check your company's policy on sending logs to an LLM before using real production logs.

## Step 6. Run the app

Linux or macOS:

```bash
# optional: use the read-only kubeconfig from step 4
export DEVOPS_KONNEKT_KUBECONFIG="$PWD/secrets/devops-konnekt-readonly.kubeconfig"
.venv/bin/python -m streamlit run app.py
```

Windows:

```powershell
$env:DEVOPS_KONNEKT_KUBECONFIG = "$PWD\secrets\devops-konnekt-readonly.kubeconfig"   # skip to use your normal kubeconfig
.venv\Scripts\python.exe -m streamlit run app.py
```

Open http://localhost:8501. The server listens on `127.0.0.1` only (set in `.streamlit/config.toml`), because the app has no login of its own. Don't change that to expose it on a network.

`DEVOPS_KONNEKT_KUBECONFIG` only lasts for that terminal. Set it again in a new one. Without it, the app uses your current kubectl context.

**After you change any code file, stop the app (`Ctrl+C`) and start it again.** Python loads the files once at startup, so a browser refresh alone can show old code.

## How to use it

**Check the Cluster card first.** The left panel shows the context the app is connected to. Your kubeconfig can hold several clusters (including production). Make sure it is the one you expect.

1. On the first page, click **Developers / DevOps** or **Business team**. Use **⇄ Change role** to switch.
2. **Developers / DevOps:**
   - The pods are listed in boxes by namespace. System namespaces (`kube-system` and similar) are hidden. Turn on **Show system namespaces** to see them.
   - Click a pod. A failing pod shows, in order: **Error log lines**, **What went wrong** (the error lines in plain English), **Who caused it**, **Search by correlation ID**, and **Claude's take**.
   - **Search by correlation ID** searches that pod's recent logs (the last 2000 lines of the current and previous container) for an ID you paste. Try `3f2a9c1d-0003` on `orders-service-4e2a`.
   - **Claude's take**: click **Analyze with Claude**, read the preview, then **Approve and send**. Ask a follow-up below the answer.
3. **Business team:** click a suggested question or type your own. Answers use ✅ and ❌. Detailed or technical questions get a default message that points to the engineering team. The four suggested questions are:
   - Which of our services are working right now?
   - Is anything not working?
   - Is the checkout working for customers?
   - Did anything have a problem recently?
4. The **Light theme** switch is at the bottom of the left panel.

## Step 7. Point it at your real repos (commit lookup)

The **Who caused it** box needs two things:

1. The image tag ends in a commit ID (7 to 40 hex characters), for example `myapp:7fd1a60`. A tag like `latest` gives nothing, and the box says it can't tell which commit this runs.
2. The app knows which GitHub repo the pod belongs to. It looks in this order:
   1. `repos.json` in the project root, a map of pod-name prefix to `owner/repo`.
   2. The `DEVOPS_KONNEKT_REPOS` environment variable, the same JSON.
   3. An image path like `ghcr.io/owner/repo:sha`.

The lookup uses the **GitHub** API only. Repos on Bitbucket or GitLab are not supported.

If your CI builds `latest`, also tag the image with the commit ID in the pipeline (for example `git rev-parse --short HEAD`) and deploy with that tag. I have not verified that for your pipeline, so test it on a non-production cluster first.

The shipped `repos.json` maps `payment-service` to `octocat/Hello-World`, a **public demo repo**. Replace it with your own:

```json
{ "payment-service": "your-org/payment-service" }
```

For private repos, or to avoid GitHub's anonymous rate limit, set a token with read access to repository contents:

```bash
export GITHUB_TOKEN="<your token>"        # Windows: $env:GITHUB_TOKEN = "<your token>"
```

Never commit a token. Results are cached for 5 minutes.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| The page looks the same after editing code | Stop the app (`Ctrl+C`) and start it again. A browser refresh is not enough. |
| The Cluster card shows a name you did not expect | Stop the app. Run `kubectl config current-context` and `kubectl config use-context kind-devops-konnekt`. |
| `kind` or `kubectl` not found | Open a new terminal so `PATH` refreshes. |
| `docker ps` fails | Start Docker (Docker Desktop, or the Docker service on Linux) and wait for it to finish starting. |
| `REGDB_E_CLASSNOTREG` from WSL (Windows) | Run `wsl --install` in an administrator PowerShell, accept the prompts, reboot. |
| Dashboard shows no pods or a connection error | Check `kubectl get pods -n demo-apps`. A read-only token expires after 24 hours: rerun `make-readonly-kubeconfig.ps1` and restart the app. |
| Payment pod stuck on `ImagePullBackOff` | Do step 3b. |
| `orders-service-4e2a` stuck on `ImagePullBackOff` | The cluster can't reach Docker Hub. Check internet access. |
| Analyze shows an error, or Claude is off | Run `claude -p "hi"` in a terminal. Fix login first. If `ANTHROPIC_API_KEY` is set to something invalid, unset it. |
| Analysis is slow | It shells out to the CLI. The timeout is 240 seconds. |
| "Who caused it" says "no repo" | Add the pod to `repos.json` (step 7). |
| "Who caused it" says "rate limit" or "not found" | Set `GITHUB_TOKEN`, or check the repo name and that the commit exists in it. |
| "Who caused it" says it can't tell which commit | The image tag does not end in a commit ID (for example `latest`). Tag the image with the commit ID. |
| Correlation ID search finds nothing | The ID must appear in the pod's last 2000 log lines, as plain text. |
| Masked output shows odd `REDACTED` on harmless IDs | The long-token rule also hides pod UIDs and container IDs. Harmless. |

## Known limits

- Masking can miss secrets in formats it doesn't know. The preview is the real check.
- Prompt injection is reduced (Claude has no tools, output isn't rendered as HTML) but not eliminated. Check any command Claude suggests before running it.
- The app has no login and no audit log of what was sent to Claude.
- Correlation ID search reads only the last 2000 lines of each container, and only what Kubernetes still holds. For older history you need a log store such as Loki or Elasticsearch.
- The commit lookup works with GitHub only, and only when the image tag ends in a commit ID.
- The Business team chat answers a fixed set of simple questions. Anything else gets the default message.
- The Anthropic API backend has not been exercised live.
- The read-only kubeconfig script is PowerShell only.

## Files

| File | Purpose |
|---|---|
| `app.py` | the Streamlit app: role choice, pod list, pod details, correlation ID search, business chat |
| `llm.py` | Claude backends, prompts (code issue vs deployment issue), follow-up chat |
| `masking.py`, `test_masking.py` | secret masking and its tests |
| `gitinfo.py` | commit lookup via the GitHub API |
| `theme.py`, `.streamlit/config.toml` | Konnekt Noir styling (dark and light) and server settings |
| `sample-pods.yaml` | demo namespace and pods |
| `rbac.yaml`, `make-readonly-kubeconfig.ps1` | read-only cluster identity |
| `repos.json` | pod-name prefix to GitHub repo map (demo values) |
| `Devops-Konnekt-use-cases.pptx` | a presentation of the use cases |
