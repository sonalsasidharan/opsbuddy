# Devops-Konnekt: set up, recreate the pods, and run it locally

This guide takes you from nothing to a running app with demo pods, and shows how to reset the demo. It uses Linux or macOS commands. Windows differences are noted. For what the app does and how to use it, see the [README](../README.md).

**Before every `kubectl` command, check which cluster you are on:**

```bash
kubectl config current-context
```

Your kubeconfig can hold real clusters (GKE, EKS, production). The commands below name the demo cluster explicitly where possible. For the demo it must print `kind-devops-konnekt`.

---

## 1. Check the tools

```bash
docker ps                 # must print a table (it can be empty), not an error
kind version
kubectl version --client
python3 --version         # 3.10 or newer
git --version
```

If one is missing, install it from its official documentation (macOS: `brew install kind kubectl`). On Windows, use Docker Desktop and `winget install -e --id Kubernetes.kind` and `Kubernetes.kubectl`, then open a new terminal.

## 2. Get the code and set up Python (once)

```bash
git clone <this-repo-url> devops-konnekt
cd devops-konnekt
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python test_masking.py        # must print FAILURES: 0
```

Windows: use `python -m venv .venv` and `.venv\Scripts\python.exe` instead of `.venv/bin/python`.

## 3. Create the cluster and the demo pods

```bash
kind create cluster --name devops-konnekt
kubectl config use-context kind-devops-konnekt
kubectl config current-context          # must print kind-devops-konnekt
kubectl apply -f sample-pods.yaml
kubectl get pods -n demo-apps
```

The cluster is `devops-konnekt`, the kubectl context is `kind-devops-konnekt`, and the Docker container is `devops-konnekt-control-plane`.

After about a minute you should see:

| Pod | Expected state | What it is for |
|---|---|---|
| `healthy-api-7d9f` | `Running` | a healthy service |
| `payment-service-5c8b` | `ImagePullBackOff` (or a crash, after step 4) | a database connection error with fake secrets, to test masking |
| `orders-service-4e2a` | `CrashLoopBackOff` | a Python code bug (`KeyError`), a correlation ID `3f2a9c1d-0003` and a made-up committer line in its logs |
| `promo-service-3a1d` | `ImagePullBackOff` | a bad image on purpose |

`orders-service-4e2a` pulls `python:3.12-alpine` from Docker Hub, so the cluster needs internet access.

## 4. (Optional) Make the payment pod's image pullable

The payment pod's image is `localhost:5001/payment-service:7fd1a60`. A kind node can't pull from your machine's `localhost`, so run a small local registry and point the node at it:

```bash
docker run -d --restart=always -p 127.0.0.1:5001:5000 --network kind --name kind-registry registry:2
docker pull busybox:1.36
docker tag busybox:1.36 localhost:5001/payment-service:7fd1a60
docker push localhost:5001/payment-service:7fd1a60
docker exec devops-konnekt-control-plane mkdir -p /etc/containerd/certs.d/localhost:5001
docker exec devops-konnekt-control-plane sh -c 'printf "[host.\"http://kind-registry:5000\"]\n" > /etc/containerd/certs.d/localhost:5001/hosts.toml'
kubectl --context kind-devops-konnekt delete pod payment-service-5c8b -n demo-apps
kubectl --context kind-devops-konnekt apply -f sample-pods.yaml
```

If `docker run` says the name `kind-registry` is already in use, the registry exists. Skip that first line. On Windows PowerShell, write the `hosts.toml` file and copy it in, as described in the README.

The payment pod should now crash on purpose (`CrashLoopBackOff`) instead of showing `ImagePullBackOff`. You can skip this step. The app works without it.

## 5. (Optional) Use a read-only cluster identity

The app only reads from the cluster. For a real cluster, give it a read-only identity (`rbac.yaml` allows get and list on pods, events and namespaces, and get on pod logs). The helper script is PowerShell only:

```powershell
powershell -ExecutionPolicy Bypass -File .\make-readonly-kubeconfig.ps1
```

It writes `secrets/devops-konnekt-readonly.kubeconfig` with a 24-hour token. On Linux or macOS you would do the same steps by hand. That has not been tested.

## 6. Run the app locally

```bash
# optional: use the read-only kubeconfig from step 5
export DEVOPS_KONNEKT_KUBECONFIG="$PWD/secrets/devops-konnekt-readonly.kubeconfig"

.venv/bin/python -m streamlit run app.py
```

Open http://localhost:8501. The server listens on `127.0.0.1` only, because the app has no login.

- Without `DEVOPS_KONNEKT_KUBECONFIG`, the app uses your **current kubectl context**.
- **Check the Cluster card in the left panel.** It must say `kind-devops-konnekt`. If it shows another name, press `Ctrl+C` to stop the app and fix the context.
- After you change any code file, stop the app (`Ctrl+C`) and start it again. A browser refresh alone can show old code.

For Claude analysis, install Claude Code and log in once (`claude`), as described in the README. The app works without it, except for the **Analyze with Claude** button.

## 7. Try the demo

1. On the first page, click **Developers / DevOps**.
2. Open the `demo-apps` box, then click `orders-service-4e2a`.
3. You should see, in order: **Error log lines**, **What went wrong** (in plain English), **Who caused it**, **Search by correlation ID**, and **Claude's take**.
4. In **Search by correlation ID**, paste `3f2a9c1d-0003` and press Search. You should see the `ERROR correlation_id=...` line. Search `3f2a9c1` or `Asha` to find the made-up committer line.
5. Click **⇄ Change role**, then **Business team**. Click one of the four suggested questions.

**Who caused it** only finds a commit if the image tag ends in a commit ID and the repo is in `repos.json`. `orders-service-4e2a` has neither, so its box says it can't tell which commit. `payment-service-5c8b` (tag `7fd1a60`) is mapped to a public demo repo and needs internet access and the registry from step 4.

---

## Recreate the demo pods only

Use this to get fresh pods without rebuilding the cluster. It deletes everything in the `demo-apps` namespace, so check the context first:

```bash
kubectl config current-context          # must print kind-devops-konnekt
kubectl --context kind-devops-konnekt delete -f sample-pods.yaml
kubectl --context kind-devops-konnekt apply -f sample-pods.yaml
kubectl --context kind-devops-konnekt get pods -n demo-apps
```

To restart one pod, for example the payment pod:

```bash
kubectl --context kind-devops-konnekt delete pod payment-service-5c8b -n demo-apps
kubectl --context kind-devops-konnekt apply -f sample-pods.yaml
```

## Recreate the whole cluster

This deletes the cluster and all its pods, then builds it again. After it, redo step 4 if you want the payment pod's image to pull.

```bash
kind delete cluster --name devops-konnekt
kind create cluster --name devops-konnekt
kubectl config use-context kind-devops-konnekt
kubectl config current-context          # must print kind-devops-konnekt
kubectl apply -f sample-pods.yaml
```

Then stop the app (`Ctrl+C`) and start it again.

## Stop and clean up

```bash
# stop the app: press Ctrl+C in its terminal
kind delete cluster --name devops-konnekt
docker rm -f kind-registry              # only if you did step 4
```

---

## Quick fixes

| Symptom | Fix |
|---|---|
| The page looks the same after a code change | Stop the app (`Ctrl+C`) and start it again. |
| The Cluster card shows an unexpected name | Stop the app. Run `kubectl config use-context kind-devops-konnekt`, then start the app again. |
| `docker ps` fails | Start Docker and wait for it to finish starting. |
| No pods, or a connection error | Run `kubectl get pods -n demo-apps`. A read-only token expires after 24 hours. |
| `payment-service-5c8b` stays `ImagePullBackOff` | Do step 4. |
| `orders-service-4e2a` stays `ImagePullBackOff` | The cluster can't reach Docker Hub. Check internet access. |
| **Analyze with Claude** shows an error | Run `claude -p "hi"` in a terminal and fix the login. If `ANTHROPIC_API_KEY` is set to something invalid, unset it. |
| Correlation ID search finds nothing | The ID must appear as plain text in the pod's last 2000 log lines. |
