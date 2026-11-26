# dummy-ui-app

A tiny web app (Python standard library only) for trying Devops-Konnekt. It runs as a Deployment in the `demo-apps` namespace, so its pod shows up in the dashboard. Every request is logged with a correlation ID.

| URL | What it does |
|---|---|
| `/` | a simple page |
| `/health` | returns `ok` |
| `/error` | logs an `ERROR correlation_id=...` line and returns HTTP 500. The pod keeps running. |

Before you start: the demo cluster and `demo-apps` namespace exist (`../docs/SETUP.md`, steps 3 and 4, including the local registry on `localhost:5001`), and `kubectl config current-context` prints `kind-devops-konnekt`.

## 1. Build and push the image

```bash
cd dummy-ui-app
docker build -t localhost:5001/dummy-ui:latest .
docker push localhost:5001/dummy-ui:latest
```

## 2. Deploy it

```bash
kubectl --context kind-devops-konnekt apply -f deployment.yaml
kubectl --context kind-devops-konnekt get pods -n demo-apps
```

You should see a pod named `dummy-ui-<random>` with state `Running`. It also appears in the `demo-apps` box in Devops-Konnekt.

## 3. Open it on localhost

The app listens on port 8080 inside the pod. Forward it to a free port on your machine (this example uses 8081, because 8080 is often taken):

```bash
kubectl --context kind-devops-konnekt port-forward deployment/dummy-ui 8081:8080 -n demo-apps
```

Open http://localhost:8081. Click the links, and use **Trigger an error** (`/error`) to write an ERROR line to the logs. In Devops-Konnekt, open the `dummy-ui` pod and watch **Live logs**.

```bash
kubectl --context kind-devops-konnekt logs deployment/dummy-ui -n demo-apps
```

Devops-Konnekt is on port 8501, so it doesn't clash with this app.

## 4. Add a bug, rebuild, and watch the dashboard

1. Open `app.py` and uncomment the line shown in the "add a bug here" block, or add your own error.
2. Rebuild and push the same image name, then restart the pod:

```bash
docker build -t localhost:5001/dummy-ui:latest .
docker push localhost:5001/dummy-ui:latest
kubectl --context kind-devops-konnekt rollout restart deployment/dummy-ui -n demo-apps
kubectl --context kind-devops-konnekt get pods -n demo-apps
```

The new pod should start, fail and go to `CrashLoopBackOff`. In Devops-Konnekt, refresh the page and open the new `dummy-ui` pod: you should see the error log lines, the plain-English "What went wrong", and Claude's take. The deployment uses `imagePullPolicy: Always`, so the restarted pod pulls the new image.

To go back to the working version, remove the bug, rebuild, push and restart the same way.

## Remove it

```bash
kubectl --context kind-devops-konnekt delete -f deployment.yaml
```
