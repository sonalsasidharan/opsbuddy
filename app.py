import json
import os
import re
from datetime import datetime, timezone

import streamlit as st
import streamlit.components.v1 as components
from kubernetes import client, config

import gitinfo
import llm
import masking
from theme import CSS, LIGHT_CSS, esc, inline, mark

st.set_page_config(page_title="Devops-Konnekt", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)
if st.session_state.get("light"):
    st.markdown(LIGHT_CSS, unsafe_allow_html=True)


# --- Connect to Kubernetes (~/.kube/config) ---
@st.cache_resource
def get_k8s_clients():
    # Point DEVOPS_KONNEKT_KUBECONFIG at a read-only kubeconfig (see rbac.yaml) instead of your admin one.
    config.load_kube_config(config_file=os.environ.get("DEVOPS_KONNEKT_KUBECONFIG") or None)
    return client.CoreV1Api(), client.AppsV1Api()


v1, apps_v1 = get_k8s_clients()

# Map technical pod prefixes to friendly business names for PMs/Marketing
BUSINESS_MAP = {
    "healthy-api": "Checkout & Storefront",
    "payment-service": "Payment Gateway",
    "promo-service": "Marketing Promo Engine",
}


def get_friendly_name(pod_name: str) -> str:
    for prefix, label in BUSINESS_MAP.items():
        if pod_name.startswith(prefix):
            return label
    return pod_name


def mask_secrets(text: str) -> str:
    """Scrubs secrets and personal data before showing text. See masking.py for what it covers."""
    return masking.mask_text(text)


def format_age(start_time) -> str:
    if not start_time:
        return "N/A"
    delta = datetime.now(timezone.utc) - start_time
    mins = int(delta.total_seconds() // 60)
    if mins < 60:
        return f"{mins}m"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h {mins % 60}m"
    return f"{hours // 24}d"


def get_namespaces() -> list:
    try:
        return sorted(ns.metadata.name for ns in v1.list_namespace().items)
    except Exception:
        return ["demo-apps", "default"]


def fetch_cluster_state(namespace: str) -> list:
    pods = v1.list_namespaced_pod(namespace).items
    results = []
    for p in pods:
        name = p.metadata.name
        state = p.status.phase
        reason = None
        exit_code = None
        restarts = 0
        cpu_req = "none"
        mem_req = "none"
        image = None

        if p.spec.containers:
            image = p.spec.containers[0].image
            res = p.spec.containers[0].resources
            if res and res.requests:
                cpu_req = res.requests.get("cpu", "none")
                mem_req = res.requests.get("memory", "none")

        if p.status.container_statuses:
            cs = p.status.container_statuses[0]
            restarts = cs.restart_count
            if cs.state.waiting and cs.state.waiting.reason:
                state = cs.state.waiting.reason
                reason = cs.state.waiting.message
            elif cs.state.terminated:
                state = cs.state.terminated.reason or "Terminated"
                exit_code = cs.state.terminated.exit_code
            elif cs.last_state.terminated:
                reason = cs.last_state.terminated.reason
                exit_code = cs.last_state.terminated.exit_code

        is_healthy = state == "Running" and restarts < 2
        results.append({
            "pod_name": name,
            "uid": p.metadata.uid,
            "business_name": get_friendly_name(name),
            "state": state,
            "restarts": restarts,
            "reason": reason,
            "exit_code": exit_code,
            "node": p.spec.node_name or "unscheduled",
            "age": format_age(p.status.start_time),
            "resources": f"CPU: {cpu_req} | Mem: {mem_req}",
            "image": image,
            "healthy": is_healthy,
        })
    return results



@st.cache_data(ttl=10, show_spinner=False)
def cached_state(namespace: str) -> list:
    """Pod states for the namespace-grouped list (cached briefly so the list stays quick)."""
    return fetch_cluster_state(namespace)


def _read_logs(pod_name: str, namespace: str) -> str:
    """Previous container logs first, then current. The API sometimes returns an
    'unable to retrieve container logs' string instead of raising, so treat that as a miss."""
    for previous in (True, False):
        try:
            logs = v1.read_namespaced_pod_log(pod_name, namespace, previous=previous, tail_lines=150)
        except Exception:
            continue
        if logs and not logs.startswith("unable to retrieve container logs"):
            return logs
    return ""


def get_top_errors(pod_name: str, namespace: str, lines: int = 10, mask: bool = True) -> str:
    raw_logs = _read_logs(pod_name, namespace)
    if not raw_logs:
        return "No logs yet. The container has not started, so there is nothing to read."
    err_lines = [
        l for l in raw_logs.splitlines()
        if re.search(r"ERROR|Exception|Fatal|panic|Traceback|Failed|WARN", l, re.IGNORECASE)
    ]
    selected = err_lines[-lines:] if err_lines else raw_logs.splitlines()[-lines:]
    out = "\n".join(selected)
    return mask_secrets(out) if mask else out


def get_pod_events(namespace: str, pod_prefix: str = "", uid: str | None = None) -> list:
    events = v1.list_namespaced_event(namespace).items
    warnings = []
    for ev in events:
        obj_name = ev.involved_object.name or ""
        if pod_prefix and pod_prefix not in obj_name:
            continue
        # Skip events from an earlier pod that had the same name.
        if uid and ev.involved_object.uid and ev.involved_object.uid != uid:
            continue
        if ev.type == "Warning":
            warnings.append(f"- **{ev.reason}** on `{obj_name}`: {ev.message}")
    return warnings[-8:]


@st.cache_data(ttl=300, show_spinner=False)
def cached_commit_info(repo: str, sha: str) -> dict:
    return gitinfo.fetch_commit_info(repo, sha)


def commit_for_pod(pod: dict) -> dict:
    """Look up the commit behind a pod's image. Always returns a dict with 'status'."""
    sha = gitinfo.extract_sha(pod.get("image"))
    if not sha:
        return {"status": "no_sha", "image": pod.get("image")}
    repo = gitinfo.resolve_repo(pod["pod_name"], pod.get("image"))
    if not repo:
        return {"status": "no_repo", "sha": sha}
    info = cached_commit_info(repo, sha)
    if "error" in info:
        return {"status": "error", "sha": sha, "repo": repo, "error": info["error"]}
    return {"status": "ok", "repo": repo, **info}


def explain_root_cause(err_text: str, state: str = "") -> tuple[str, str]:
    """Returns (Plain-English Summary for PMs/Devs, DevOps Actionable Hint)."""
    lower = f"{err_text} {state}".lower()
    if "connection refused" in lower or "5432" in lower or "3306" in lower:
        return (
            "The application cannot connect to its database, so it fails on startup.",
            "Check DB Service endpoints (`kubectl get ep`), NetworkPolicies, and the DB credentials Secret."
        )
    if "oomkilled" in lower or "memory" in lower or "exit code 137" in lower:
        return (
            "The container used more memory than allowed and was stopped by Kubernetes.",
            "Inspect the memory profile and raise `resources.limits.memory` in the Deployment manifest."
        )
    if "imagepullbackoff" in lower or "errimagepull" in lower:
        return (
            "Kubernetes could not download the container image.",
            "Verify the image tag exists in the registry and check `imagePullSecrets` permissions."
        )
    if "nullpointer" in lower or "exception" in lower or "traceback" in lower:
        return (
            "An unhandled code error crashed the process.",
            "Share the stack trace line number with the owning developer, or roll back the last release."
        )
    return (
        "The container hit a fatal error while running or starting.",
        "Inspect Kubernetes warning events and environment variables or ConfigMaps."
    )


def find_target_pod(query: str, cluster_state: list):
    for p in cluster_state:
        prefix = p["pod_name"].split("-")[0]
        if prefix in query or p["pod_name"].lower() in query or p["business_name"].lower() in query:
            return p
    crashing = [p for p in cluster_state if not p["healthy"]]
    return crashing[0] if crashing else None


def named_pod(query: str, cluster_state: list):
    for p in cluster_state:
        if p["pod_name"].lower() in query or p["pod_name"].rsplit("-", 1)[0] in query or p["business_name"].lower() in query:
            return p
    return None


def commit_markdown(pod: dict, ci: dict) -> str:
    head = f"### Commit behind `{pod['pod_name']}` ({pod['business_name']})\n"
    if ci["status"] == "no_sha":
        return head + (
            f"I can't tell which commit this pod runs. Its image `{ci['image']}` has a tag that doesn't end in a commit SHA. "
            "Tag images with the commit SHA (for example `payment-service:3f2a9c1`) and I can find the author."
        )
    if ci["status"] == "no_repo":
        return head + (
            f"The image tag points to commit `{ci['sha'][:7]}`, but I don't know which repository it belongs to. "
            "Add the service to `repos.json`, for example `{\"payment-service\": \"owner/repo\"}`."
        )
    if ci["status"] == "error":
        return head + f"The image points to `{ci['sha'][:7]}` in `{ci['repo']}`, but: {ci['error']}"
    c = ci["commit"]
    who = f"{c['author']}" + (f" (@{c['login']})" if c["login"] else "")
    out = [
        head,
        f"- **Author:** {who}",
        f"- **Commit:** [`{c['short']}`]({c['url']}), {c['message']}",
        f"- **Committed:** {c['date']}",
        f"- **Repository:** `{ci['repo']}`",
    ]
    if ci["previous"]:
        out.append("\n**Just before it:**")
        for pc in ci["previous"]:
            out.append(f"- [`{pc['short']}`]({pc['url']}) {pc['message']} ({pc['author']})")
    out.append(
        "\nThis is the commit the running image was built from, so it is the most likely suspect. "
        "It isn't proof. Check its diff against the error before assigning blame."
    )
    return "\n".join(out)


def build_ai_context(pod: dict, namespace: str) -> tuple[str, dict]:
    """Trimmed diagnostics for the LLM, masked as one piece. Returns (text, what was masked)."""
    logs = get_top_errors(pod["pod_name"], namespace, lines=15, mask=False)
    events = get_pod_events(namespace, pod["pod_name"].split("-")[0], pod.get("uid"))
    ci = commit_for_pod(pod)
    parts = [
        f"Pod: {pod['pod_name']} (service: {pod['business_name']})",
        f"State: {pod['state']}; restarts: {pod['restarts']}; exit code: {pod['exit_code']}; age: {pod['age']}",
        f"Waiting message: {pod['reason']}",
        f"Image: {pod['image']}",
        f"Resource requests: {pod['resources']}",
        "",
        "Error log lines:",
        logs,
        "",
        "Last log lines (these include stack trace frames, so file names and line numbers):",
        "\n".join(_read_logs(pod["pod_name"], namespace).splitlines()[-25:]) or "none",
        "",
        "Warning events:",
        "\n".join(events) if events else "none",
        "",
    ]
    if ci["status"] == "ok":
        c = ci["commit"]
        parts.append(f"Suspected commit (the image was built from it): {c['short']} by {c['author']} on {c['date']}: {c['message']}")
    else:
        parts.append("Suspected commit: unknown")
    return masking.mask("\n".join(parts))


def ai_key(pod: dict, namespace: str) -> tuple:
    return (namespace, pod["pod_name"], pod["state"], pod["restarts"], pod.get("image"))


def cached_analysis(pod: dict, namespace: str):
    return st.session_state.get("ai_cache", {}).get(ai_key(pod, namespace))


def ai_analysis(pod: dict, namespace: str, context: str) -> dict:
    """Send the already-previewed, already-masked `context` to Claude and cache the answer.
    Cached per pod state so a rerun doesn't bill twice."""
    cache = st.session_state.setdefault("ai_cache", {})
    key = ai_key(pod, namespace)
    with st.spinner("Claude is analyzing the failure..."):
        result = llm.analyze(context)
    if "text" in result:  # don't cache failures
        result["context"] = context  # follow-up questions reuse this exact snapshot
        cache[key] = result
        st.session_state.setdefault("followups", {})[key] = []  # fresh analysis, fresh conversation
    return result


COMPLEX_REPLY = (
    "That's a detailed question, so I can't answer it here. Please ask the engineering / DevOps team.\n\n"
    "I can help with basic questions about your services, for example:\n"
    "- *\"Which of our services are working right now?\"*\n"
    "- *\"Is anything not working?\"*\n"
    "- *\"Is the checkout working for customers?\"*\n"
    "- *\"Did anything have a problem recently?\"*"
)
# Technical topics (fixes, causes, logs, events, resources) are handled by the engineers, not in this chat.
COMPLEX_TOPICS = re.compile(
    r"\b(fix|suggest|recommend|how do i|how to|resolve|solution|root cause|commit|author|blame|culprit|who|pushed|"
    r"caused|broke|errors?|logs?|stack|trace|debug|why|events?|warnings?|describe|resources?|cpu|memory|node|restarts?)\b"
)


def generate_reply(user_prompt: str, cluster_state: list, namespace: str) -> str:
    q = user_prompt.lower()
    crashing = [p for p in cluster_state if not p["healthy"]]
    running = [p for p in cluster_state if p["state"] == "Running"]

    if COMPLEX_TOPICS.search(q):
        return COMPLEX_REPLY

    # AI: cause and fix suggestions
    if any(w in q for w in ["fix", "suggest", "recommend", "how do i", "how to", "resolve", "solution", "root cause"]):
        target = find_target_pod(q, cluster_state)
        if not target:
            return f"Nothing is failing in `{namespace}` right now, so there is nothing to fix."
        # Sending data to Claude always goes through the preview in Pod details, never from chat.
        result = cached_analysis(target, namespace)
        if result:
            return f"### Claude analysis for `{target['pod_name']}` ({target['business_name']})\n\n{result['text']}"
        return (
            f"I can ask Claude about `{target['pod_name']}`, but first you need to see exactly what would be sent. "
            "Open the pod under **Pod details** and click **Analyze with Claude**: it shows a preview and waits for your approval."
        )

    # 0. Who broke it: Git commit and author
    if any(w in q for w in ["commit", "author", "blame", "culprit", "who ", "who's", "pushed", "caused", "broke"]):
        target = named_pod(q, cluster_state)
        targets = [target] if target else crashing
        if not targets:
            return f"Nothing is failing in `{namespace}` right now, so there is no commit to look into."
        return "\n\n".join(commit_markdown(p, commit_for_pod(p)) for p in targets)

    # 1. Developer / DevOps: Top Error Logs
    if any(w in q for w in ["error", "log", "stack", "trace", "lines", "debug", "why"]):
        target = find_target_pod(q, cluster_state)
        if not target:
            return f"No failing pods in `{namespace}` right now."
        logs = get_top_errors(target["pod_name"], namespace, lines=10)
        summary, devops_tip = explain_root_cause(logs, target["state"])
        return (
            f"### Diagnostics for `{target['pod_name']}` ({target['business_name']})\n"
            f"- **Status:** `{target['state']}`, **restarts:** `{target['restarts']}`, **node:** `{target['node']}`\n"
            f"- **What happened:** {summary}\n"
            f"- **What to check:** {devops_tip}\n\n"
            f"**Top 10 error lines (secrets masked):**\n```text\n{logs}\n```\n"
            f"Ask *\"who caused {target['pod_name'].rsplit('-', 1)[0]}\"* to see the commit behind it."
        )

    # 2. DevOps / Developer: Kubernetes Events & Describe Info
    if any(w in q for w in ["event", "warning", "describe", "resource", "cpu", "memory", "node", "restart"]):
        target = find_target_pod(q, cluster_state)
        prefix = target["pod_name"].split("-")[0] if target else ""
        warnings = get_pod_events(namespace, prefix)
        lines = [f"### Cluster and events in `{namespace}`\n"]
        for p in cluster_state:
            mark_ = "Healthy" if p["healthy"] else "Needs attention"
            lines.append(
                f"- `{p['pod_name']}`: **{p['state']}** ({mark_}), restarts `{p['restarts']}`, "
                f"age `{p['age']}`, node `{p['node']}`, requests `{p['resources']}`"
            )
        lines.append("\n**Recent warning events:**")
        lines.extend(warnings if warnings else ["- None recorded in this namespace."])
        return "\n".join(lines)

    # 3. Count / Inventory Queries
    if any(w in q for w in ["how many", "count", "total", "number of"]):
        return (
            f"### Pods in `{namespace}`\n"
            f"- **Total:** `{len(cluster_state)}`\n"
            f"- ✅ **Running and healthy:** `{len(running)}`\n"
            f"- ❌ **Needs attention:** `{len(crashing)}`"
        )

    # Business questions in plain language
    if any(w in q for w in ["recently", "problem", "earlier", "yesterday", "today"]):
        if not cluster_state:
            return f"No services are deployed in `{namespace}`."
        issues = [p for p in cluster_state if not p["healthy"] or p["restarts"] > 0]
        if not issues:
            return "### ✅ No problems seen\nAll services are healthy and none have restarted."
        lines = ["### Services that had a problem\n"]
        for p in issues:
            mark_ = "✅" if p["healthy"] else "❌"
            note = "working now, but it restarted" if p["healthy"] else f"not working now ({p['state']})"
            lines.append(f"- {mark_} **{p['business_name']}**: {note}, `{p['restarts']}` restarts")
        lines.append("\n*I only know restart counts since each service started. I don't keep a history of outages.*")
        return "\n".join(lines)

    if any(w in q for w in ["not working", "anything wrong", "anything broken", "anything down", "any issue", "any problem"]):
        if not cluster_state:
            return f"No services are deployed in `{namespace}`."
        if not crashing:
            return "### ✅ Everything is working\nAll services are healthy."
        lines = [f"### ❌ {len(crashing)} service(s) not working\n"]
        for p in crashing:
            lines.append(f"- ❌ **{p['business_name']}**: {p['state']}")
        return "\n".join(lines)

    if "working right now" in q or ("which" in q and "services" in q and "working" in q):
        if not cluster_state:
            return f"No services are deployed in `{namespace}`."
        ok = [p for p in cluster_state if p["healthy"]]
        if not ok:
            return "### ❌ None of the services are working right now"
        lines = [f"### Working right now ({len(ok)} of {len(cluster_state)})\n"]
        lines.extend(f"- ✅ **{p['business_name']}**" for p in ok)
        return "\n".join(lines)

    # 3a. Basic pod questions: which pods are not healthy / how long have they been running
    if any(w in q for w in ["not healthy", "unhealthy", "failing", "not running", "need attention", "broken"]):
        if not cluster_state:
            return f"No pods in `{namespace}`."
        if not crashing:
            return f"### ✅ All {len(cluster_state)} pods in `{namespace}` are healthy"
        lines = [f"### Pods that are not healthy in `{namespace}`\n"]
        for p in crashing:
            lines.append(f"- ❌ `{p['pod_name']}` ({p['business_name']}): **{p['state']}**, `{p['restarts']}` restarts")
        return "\n".join(lines)

    if any(w in q for w in ["how long", "running for", "uptime", "age of"]):
        if not cluster_state:
            return f"No pods in `{namespace}`."
        rows = ["| Pod | Running for | Restarts |", "|---|---|---|"]
        for p in cluster_state:
            rows.append(f"| {'✅' if p['healthy'] else '❌'} `{p['pod_name']}` | {p['age']} | {p['restarts']} |")
        return f"### How long each pod has been running in `{namespace}`\n\n" + "\n".join(rows)

    # 3b. Business: is one named service ready for customers?
    named = next(
        (p for p in cluster_state
         if p["pod_name"].split("-")[0] in q or p["business_name"].lower() in q
         or any(len(w) > 3 and w in q for w in re.findall(r"[a-z]+", p["business_name"].lower()))),
        None,
    )
    if named and any(w in q for w in ["ready", "customer", "working", "down", "available", "live"]):
        if named["healthy"]:
            return (
                f"### ✅ Yes, **{named['business_name']}** is ready for customers\n"
                f"It is operational and has been running for `{named['age']}` with `{named['restarts']}` restarts. "
                "No action is needed."
            )
        return (
            f"### ❌ No, **{named['business_name']}** is not ready for customers\n"
            f"It is **degraded** (`{named['state']}`, `{named['restarts']}` restarts), so customers may see errors or delays. "
            "Please check with the engineering team for a time estimate."
        )

    # 3c. Business: status of all services at a glance (a table, not a launch verdict)
    if "status" in q and "launch" not in q:
        if not cluster_state:
            return f"No services are deployed in `{namespace}`."
        rows = ["| Pod | Service | Status |", "|---|---|---|"]
        for p in cluster_state:
            status = "✅ Healthy" if p["healthy"] else f"❌ {p['state']}"
            rows.append(f"| `{p['pod_name']}` | {p['business_name']} | {status} |")
        return f"### Status of all pods in `{namespace}`\n\n" + "\n".join(rows)

    # 4. Stakeholder / Marketing / General Status Check
    if any(w in q for w in ["launch", "campaign", "marketing", "healthy", "status", "ready", "incident", "pod"]) or re.search(r"\bup\b", q):
        if not cluster_state:
            return f"No pods are deployed in `{namespace}`."
        if not crashing:
            lines = [f"**Everything in `{namespace}` is healthy. You're clear to launch.**\n"]
            for p in cluster_state:
                lines.append(f"- ✅ **{p['business_name']}** (`{p['pod_name']}`): operational, `{p['restarts']}` restarts")
            return "\n".join(lines)
        lines = [f"**Hold the launch. {len(crashing)} service(s) need attention.**\n"]
        for p in cluster_state:
            if p["healthy"]:
                lines.append(f"- ✅ **{p['business_name']}** (`{p['pod_name']}`): operational")
            else:
                lines.append(f"- ❌ **{p['business_name']}** (`{p['pod_name']}`): degraded ({p['state']}, {p['restarts']} restarts)")
        lines.append("\nPlease check with the engineering team before launching.")
        return "\n".join(lines)

    # 5. Anything else is treated as too detailed for this chat
    return COMPLEX_REPLY




# ---------------- UI ----------------
SAMPLE_PROMPTS = [
    "Which of our services are working right now?",
    "Is anything not working?",
    "Is the checkout working for customers?",
    "Did anything have a problem recently?",
]


def commit_card(ci: dict) -> str:
    if ci["status"] == "ok":
        c = ci["commit"]
        who = esc(c["author"]) + (f' <span class="nk-k">(@{esc(c["login"])})</span>' if c["login"] else "")
        prev = "".join(
            f'<div class="nk-note"><a href="{esc(p["url"])}" target="_blank" rel="noopener noreferrer"><code>{esc(p["short"])}</code></a> '
            f'{esc(p["message"])} <span class="nk-k">({esc(p["author"])})</span></div>'
            for p in ci["previous"]
        )
        return (
            '<div class="nk-card">'
            f'<div class="nk-line" style="margin-top:0"><span style="font-weight:600">{who}</span></div>'
            f'<div class="nk-line">'
            f'<a href="{esc(c["url"])}" target="_blank" rel="noopener noreferrer" style="color:var(--champagne);text-decoration:none"><code>{esc(c["short"])}</code></a> '
            f'{esc(c["message"])}</div>'
            f'<div class="nk-note">{esc(c["date"])} in {esc(ci["repo"])}. This commit is built into the running image, so it is the most likely suspect, not proof.</div>'
            + (f'<div class="nk-note" style="margin-top:12px">Just before it</div>{prev}' if prev else "")
            + "</div>"
        )
    msg = {
        "no_sha": "Can't tell which commit this runs: the image tag doesn't end in a commit SHA.",
        "no_repo": f"Commit {esc(ci.get('sha', '')[:7])} found in the image tag, but no repository is set for this service in repos.json.",
        "error": esc(ci.get("error", "")),
    }[ci["status"]]
    return f'<div class="nk-card"><div class="nk-note" style="margin-top:0">{msg}</div></div>'


LOG_WINDOWS = {
    "Last 5 minutes": 300, "Last 15 minutes": 900, "Last hour": 3600,
    "Last 6 hours": 21600, "Last 24 hours": 86400, "All available": None, "Custom range (UTC)": "custom",
}
_TS_RE = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?Z\s?(.*)$", re.DOTALL)
LEVEL_PATTERNS = {
    "ERROR": re.compile(r"\b(ERROR|ERR|FATAL|CRITICAL|PANIC)\b|Exception|Traceback", re.I),
    "WARN": re.compile(r"\b(WARN|WARNING)\b", re.I),
    "INFO": re.compile(r"\bINFO\b", re.I),
    "DEBUG": re.compile(r"\b(DEBUG|TRACE)\b", re.I),
}
LOG_VIEW_CAP = 500


@st.cache_data(ttl=10, show_spinner=False)
def fetch_log_lines(pod_name: str, namespace: str, previous: bool, since_seconds) -> dict:
    """Ask Kubernetes for timestamped logs. The time window (since_seconds) is applied by the API server;
    everything else (keyword, level, end time) is filtered here. No LLM is involved."""
    kwargs = {"previous": previous, "timestamps": True, "tail_lines": 5000}
    if since_seconds:
        kwargs["since_seconds"] = int(since_seconds)
    try:
        raw = v1.read_namespaced_pod_log(pod_name, namespace, **kwargs)
    except Exception as e:
        return {"error": f"Kubernetes could not return logs: {getattr(e, 'reason', None) or str(e)[:200]}"}
    if not raw or raw.startswith("unable to retrieve container logs"):
        return {"lines": []}
    lines = []
    for ln in raw.splitlines():
        m = _TS_RE.match(ln)
        ts = None
        if m:
            try:
                ts = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        lines.append((ts, ln))
    return {"lines": lines}


def filter_log_lines(lines, keyword="", use_regex=False, case=False, levels=(), start=None, end=None):
    """Returns (matches, error). A line must pass every active filter."""
    pat = None
    if keyword:
        try:
            pat = re.compile(keyword if use_regex else re.escape(keyword), 0 if case else re.I)
        except re.error as e:
            return [], f"That regular expression isn't valid: {e}"
    out = []
    for ts, ln in lines:
        if (start or end) and ts is None:
            continue
        if start and ts < start:
            continue
        if end and ts > end:
            continue
        if levels and not any(LEVEL_PATTERNS[lv].search(ln) for lv in levels):
            continue
        if pat and not pat.search(ln):
            continue
        out.append(ln)
    return out, None


_PLAIN_RULES = [
    (re.compile(r"connection refused.*?([\w.-]+):(\d+)", re.I), lambda m: f"Could not connect to `{m.group(1)}` on port {m.group(2)}. That service may be down or unreachable."),
    (re.compile(r"could not connect to (?:the )?database", re.I), lambda m: "The program could not connect to its database."),
    (re.compile(r"modulenotfounderror: no module named '?([\w.]+)'?", re.I), lambda m: f"A code library the program needs (`{m.group(1)}`) is not installed."),
    (re.compile(r"keyerror: ?'?([^']+)'?", re.I), lambda m: f"The code looked for a value called `{m.group(1)}`, but it does not exist."),
    (re.compile(r"zerodivisionerror", re.I), lambda m: "The code tried to divide a number by zero."),
    (re.compile(r"attributeerror: (.*)", re.I), lambda m: f"The code used something that does not exist on an object ({m.group(1)})."),
    (re.compile(r"typeerror: (.*)", re.I), lambda m: f"The code used a value of the wrong type ({m.group(1)})."),
    (re.compile(r"valueerror: (.*)", re.I), lambda m: f"The code received a value it could not accept ({m.group(1)})."),
    (re.compile(r"(?:filenotfound|no such file)", re.I), lambda m: "A file the program needs is missing."),
    (re.compile(r"permission denied|forbidden|unauthorized", re.I), lambda m: "Access was denied. The program does not have permission."),
    (re.compile(r"timed? ?out|timeout", re.I), lambda m: "A request took too long and timed out."),
    (re.compile(r"out of memory|oomkilled|memoryerror", re.I), lambda m: "The program ran out of memory and was stopped."),
    (re.compile(r"authorization:|bearer |token=|password=", re.I), lambda m: "This line contains a login token or password, which is hidden for safety."),
    (re.compile(r"traceback", re.I), lambda m: "The program crashed because of an error in its code."),
    (re.compile(r"\bfatal\b|\bpanic\b|exception", re.I), lambda m: "The program hit an unexpected error and stopped."),
]


def plain_english_errors(logs: str, state: str) -> list:
    """Rule-based, local translation of the error log lines. Nothing is sent anywhere."""
    if logs.startswith("No logs yet"):
        return [explain_root_cause("", state)[0]]
    out = []
    for line in logs.splitlines():
        line = line.strip()
        if not line:
            continue
        for pat, fn in _PLAIN_RULES:
            m = pat.search(line)
            if m:
                msg = fn(m)
                break
        else:
            msg = f"The program reported: `{line[:140]}`"
        if msg not in out:
            out.append(msg)
    return out or [explain_root_cause(logs, state)[0]]


SYSTEM_NAMESPACES = {"kube-system", "kube-public", "kube-node-lease", "local-path-storage"}


def is_system_namespace(ns: str) -> bool:
    """Namespaces Kubernetes (and kind) create for themselves, not your own apps."""
    return ns in SYSTEM_NAMESPACES or ns.startswith("kube-")


def search_logs_by_id(pods: list, namespace: str, needle: str, per_pod: int = 30) -> tuple[list, int]:
    """Find log lines containing `needle` (for example a correlation ID) in every pod of the namespace.
    Reads the last 2000 lines of the current and the previous container. Returns ([(pod, [lines])], pods_searched)."""
    needle_l = needle.lower()
    hits = []
    for p in pods:
        lines = []
        for previous in (False, True):
            try:
                raw = v1.read_namespaced_pod_log(p["pod_name"], namespace, previous=previous, tail_lines=2000)
            except Exception:
                continue
            for ln in (raw or "").splitlines():
                if needle_l in ln.lower() and ln not in lines:
                    lines.append(ln)
        if lines:
            hits.append((p, masking.mask_text("\n".join(lines[-per_pod:])).splitlines()))
    return hits, len(pods)


def render_correlation_search(pods: list, namespace: str, key: str = "list"):
    """pods: every pod in the namespace (main page) or just the open pod (pod details)."""
    where = f"the pod <b>{esc(pods[0]['pod_name'])}</b>" if len(pods) == 1 else f"every pod in <b>{esc(namespace)}</b>"
    with st.container(key=f"corrbox-{key}"):
        st.markdown('<div class="nk-corr-h">Search by correlation ID</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="nk-note" style="margin:-2px 0 8px 0">Looks through the recent logs of {where}. '
            'Read straight from Kubernetes; nothing is sent to Claude. Secrets are masked.</div>',
            unsafe_allow_html=True,
        )
        with st.form(f"corr-form-{key}", border=False):
            c1, c2 = st.columns([5, 1])
            cid = c1.text_input("Correlation ID", placeholder="Paste a correlation ID, for example 3f2a9c1d-...", label_visibility="collapsed")
            go = c2.form_submit_button("Search", use_container_width=True)
        if go:
            cid = cid.strip()
            if len(cid) < 4:
                st.warning("Enter at least 4 characters.")
            else:
                with st.spinner("Searching logs..."):
                    hits, searched = search_logs_by_id(pods, namespace, cid)
                if not hits:
                    st.info(f"No log lines containing that ID in {searched} pod(s). Only the last 2000 lines of each pod are searched.")
                for p, lines in hits:
                    st.markdown(f"**{esc(p['business_name'])}** (`{esc(p['pod_name'])}`): {len(lines)} line(s)")
                    st.code("\n".join(lines), language="text")


COPY_ICON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
             'stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2.5"/><path d="M5 15V6.5A2.5 2.5 0 0 1 7.5 4H15"/></svg>')
TICK_ICON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
             'stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>')


def copy_button(text: str) -> None:
    """A small ChatGPT-style copy icon. One click copies `text` to the clipboard and shows a tick."""
    payload = json.dumps(text).replace("</", "<\\/")
    components.html(
        f"""
<style>
  html, body {{ margin:0; background:transparent; }}
  button {{ width:30px; height:30px; border:0; border-radius:8px; background:transparent; color:#9a9aa2;
           cursor:pointer; display:flex; align-items:center; justify-content:center; }}
  button:hover {{ background:rgba(128,128,128,.22); color:#c9c9d1; }}
  button:focus-visible {{ outline:2px solid #D9B26A; }}
  svg {{ width:17px; height:17px; }}
</style>
<button id="b" type="button" title="Copy" aria-label="Copy">{COPY_ICON}</button>
<script>
  const text = {payload};
  const btn = document.getElementById('b');
  const copyIcon = btn.innerHTML;
  btn.addEventListener('click', async () => {{
    try {{ await navigator.clipboard.writeText(text); }}
    catch (e) {{
      const a = document.createElement('textarea'); a.value = text; document.body.appendChild(a);
      a.select(); document.execCommand('copy'); a.remove();
    }}
    btn.innerHTML = '{TICK_ICON}';
    setTimeout(() => {{ btn.innerHTML = copyIcon; }}, 1600);
  }});
</script>
""",
        height=34,
    )


def render_pod(pod: dict, namespace: str):
    ok = pod["healthy"]
    st.markdown(
        '<div class="nk-card">'
        '<div class="nk-attn-head">'
        f'<div><div class="nk-title" style="font-size:24px">{esc(pod["business_name"])}</div><div class="nk-meta">{esc(pod["pod_name"])}</div></div>'
        f'<div class="nk-state" style="margin:0"><span class="dot {"ok" if ok else "bad"}"></span>'
        f'<span class="{"ok-t" if ok else "bad-t"}">{esc(pod["state"])}</span></div>'
        '</div>'
        '<div class="nk-facts">'
        f'<div><span>Restarts</span><b>{pod["restarts"]}</b></div>'
        f'<div><span>Running for</span><b>{esc(pod["age"])}</b></div>'
        f'<div><span>Node</span><b>{esc(pod["node"])}</b></div>'
        f'<div><span>Image</span><b>{esc(pod["image"])}</b></div>'
        '</div></div>',
        unsafe_allow_html=True,
    )

    if ok:
        st.markdown(
            f'<div class="nk-card"><div class="nk-line" style="margin-top:0"><span class="ok-t">No errors.</span> '
            f'{esc(pod["business_name"])} is running normally with {pod["restarts"]} restarts.</div></div>',
            unsafe_allow_html=True,
        )
        render_correlation_search([pod], namespace, key="pod")
        render_claude_box(pod, namespace)
        return

    logs = get_top_errors(pod["pod_name"], namespace, lines=10)
    summary, hint = explain_root_cause(logs, pod["state"])
    ci = commit_for_pod(pod)

    st.markdown('<div class="nk-h">Error log lines</div>', unsafe_allow_html=True)
    st.code(logs, language="text")
    ev = get_pod_events(namespace, pod["pod_name"].split("-")[0], pod.get("uid"))
    if ev:
        with st.expander("Kubernetes warning events"):
            st.markdown("\n".join(ev))

    st.markdown('<div class="nk-h">What went wrong</div>', unsafe_allow_html=True)
    items = "".join(f"<li>{inline(m)}</li>" for m in plain_english_errors(logs, pod["state"]))
    st.markdown(
        f'<div class="nk-card"><div class="nk-line" style="margin-top:0"><ul style="margin:0;padding-left:20px">{items}</ul></div></div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="nk-h">Who caused it</div>', unsafe_allow_html=True)
    st.markdown(commit_card(ci), unsafe_allow_html=True)

    render_correlation_search([pod], namespace, key="pod")

    render_claude_box(pod, namespace)


def build_business_context(services: list, namespace: str) -> tuple[str, dict]:
    """Service status only (no logs, no events). Masked like everything else that is sent to Claude."""
    lines = [f"Namespace: {namespace}", f"Services ({len(services)}):"]
    for p in services:
        lines.append(
            f"- {p['business_name']} (pod {p['pod_name']}): state {p['state']}, restarts {p['restarts']}, "
            f"running for {p['age']}, {'healthy' if p['healthy'] else 'needs attention'}"
        )
    return masking.mask("\n".join(lines))


BIZ_TAKE_QUESTION = (
    "Give a short plain-English summary of the current status. Say what is working, what is not working, "
    "and what the business should know or do next."
)


def render_business_claude_take(services: list, namespace: str) -> None:
    """Claude chat for the business team, at the end of the page. General questions on any topic.
    Only what the user types is sent. Nothing from the cluster is included."""
    with st.container(key="claudebox"):
        st.markdown('<div class="nk-claude-h"><span>✦</span> Claude’s take</div>', unsafe_allow_html=True)
        if not llm.backend():
            st.markdown(
                '<div class="nk-note" style="margin:-4px 0 4px 0">Claude is not available on this machine. '
                'Install and log in to Claude Code, or set ANTHROPIC_API_KEY.</div>',
                unsafe_allow_html=True,
            )
            return
        st.markdown(
            '<div class="nk-note" style="margin:-4px 0 10px 0">Ask Claude anything. Only what you type is sent. '
            'Nothing from your cluster is included.</div>',
            unsafe_allow_html=True,
        )
        chat = st.session_state.setdefault("claude_chat", [])
        for m in chat:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])
                if m["role"] == "assistant":
                    copy_button(m["content"])
        with st.form("biz-claude-form", clear_on_submit=True, border=False):
            c1, c2 = st.columns([6, 1])
            typed = c1.text_input("Your question", placeholder="Type your question here", label_visibility="collapsed")
            sent = c2.form_submit_button("Ask Claude", use_container_width=True)
        if sent and typed.strip():
            q = masking.mask_text(typed.strip())  # the same secret masking used everywhere else
            with st.spinner("Claude is thinking..."):
                res = llm.general_chat(list(chat), q)
            if "text" in res:
                chat.append({"role": "user", "content": q})
                chat.append({"role": "assistant", "content": res["text"]})
                st.rerun()
            else:
                st.error(res["error"])


def render_claude_box(pod: dict, namespace: str) -> None:
    """Claude's take on a pod, healthy or failing. Nothing is sent until the user approves the preview."""
    with st.container(key="claudebox"):
        st.markdown('<div class="nk-claude-h"><span>✦</span> Claude’s take</div>', unsafe_allow_html=True)
        if pod["healthy"]:
            note = ("Sends this pod’s state, its recent log lines (secrets masked) and warning events to Claude. "
                    "You see exactly what will be sent and approve it first.")
        else:
            note = ("Sends this pod’s state, the error lines above (secrets masked), warning events and the suspect "
                    "commit’s author and message to Claude. You see exactly what will be sent and approve it first.")
        st.markdown(f'<div class="nk-note" style="margin:-4px 0 10px 0">{note}</div>', unsafe_allow_html=True)
        cache_key = ai_key(pod, namespace)
        have = cached_analysis(pod, namespace)
        label = "Analyze again" if have else "Analyze with Claude"
        if st.button(label, key=f"ai-{pod['pod_name']}", type="primary"):
            st.session_state["preview_for"] = cache_key
        result = have
        if st.session_state.get("preview_for") == cache_key:
            ctx, report = build_ai_context(pod, namespace)
            with st.container(border=True):
                st.markdown("**This is exactly what will be sent to Claude**")
                if report:
                    found = ", ".join(f"{n} {k}" for k, n in report.items())
                    st.caption(f"Masked before showing you: {found}.")
                else:
                    st.caption("Nothing needed masking. Read it anyway: masking can miss secrets in formats it doesn't know.")
                st.code(ctx, language="text")
                a, b = st.columns(2)
                go = a.button("Approve and send", key=f"go-{pod['pod_name']}", type="primary", use_container_width=True)
                cancel = b.button("Cancel", key=f"cancel-{pod['pod_name']}", use_container_width=True)
            if cancel:
                st.session_state.pop("preview_for", None)
                st.rerun()
            if go:
                st.session_state.pop("preview_for", None)
                result = ai_analysis(pod, namespace, ctx)
        if result:
            if "error" in result:
                st.error(result["error"])
            else:
                with st.container(border=True):
                    st.markdown(result["text"])
                    st.caption(f"Written by {result['model']}. Verify before changing production.")
                copy_button(result["text"])
                render_followup(pod, cache_key, result)


FOLLOWUP_CHIPS = [
    "Explain this for a non-engineer",
    "Give me the exact commands to run",
    "Draft a message to the service owner",
]


def render_followup(pod: dict, key: tuple, analysis: dict):
    """Chat under the analysis. Each question is answered with the analysis snapshot plus prior turns."""
    st.markdown('<div class="nk-h" style="font-size:16px">Ask Claude a follow-up</div>', unsafe_allow_html=True)
    hist = st.session_state.setdefault("followups", {}).setdefault(key, [])
    history_box = st.container()

    chip = None
    cols = st.columns(len(FOLLOWUP_CHIPS))
    for i, (col, text) in enumerate(zip(cols, FOLLOWUP_CHIPS)):
        if col.button(text, key=f"chip-{pod['pod_name']}-{i}", use_container_width=True):
            chip = text
    with st.form(key=f"fu-{pod['pod_name']}", clear_on_submit=True, border=False):
        c1, c2 = st.columns([6, 1])
        typed = c1.text_input("Your question", placeholder="Ask anything about this failure", label_visibility="collapsed")
        sent = c2.form_submit_button("Send", use_container_width=True)

    st.caption("Follow-ups reuse the snapshot you approved above. What you type is masked the same way before it is sent.")
    question = chip or (masking.mask_text(typed.strip()) if sent and typed.strip() else None)
    error = None
    if question:
        with st.spinner("Claude is thinking..."):
            reply = llm.chat(analysis["context"], analysis["text"], list(hist), question)
        if "text" in reply:
            hist.append({"role": "user", "content": question})
            hist.append({"role": "assistant", "content": reply["text"]})
        else:
            error = reply["error"]

    with history_box:
        for m in hist:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])
                if m["role"] == "assistant":
                    copy_button(m["content"])
    if error:
        st.error(error)


# --- Sidebar: namespace and the pod list with health ---
def current_cluster() -> str:
    """Name of the kube context the app is connected to (same kubeconfig the app loaded)."""
    try:
        _, active = config.list_kube_config_contexts(config_file=os.environ.get("DEVOPS_KONNEKT_KUBECONFIG") or None)
        return active.get("name") or "unknown"
    except Exception:
        return "unknown"


namespaces = get_namespaces()
if st.session_state.get("ns") not in namespaces:
    st.session_state["ns"] = "demo-apps" if "demo-apps" in namespaces else namespaces[0]
selected_ns = st.session_state["ns"]  # changes when a pod in another namespace is opened
services = fetch_cluster_state(selected_ns)
names = [s["pod_name"] for s in services]
if st.session_state.get("selected") not in names:
    st.session_state["selected"] = None  # nothing is opened until the user clicks a pod

with st.sidebar:
    bad_n = sum(1 for s in services if not s["healthy"])
    good_n = len(services) - bad_n
    pct = round(100 * good_n / len(services)) if services else 0
    bar_color = "var(--green)" if bad_n == 0 else "var(--champagne)" if good_n else "var(--red)"
    st.markdown(
        f'<div class="nk-brand">{mark("warn" if bad_n else "ok", 44)}<div class="nk-brand-t">Devops-Konnekt</div></div>'
        '<div class="nk-sc nk-sc-t">'
        '<div class="nk-sc-l">Cluster</div>'
        f'<div class="nk-sc-v">{esc(current_cluster())}</div>'
        '<div class="nk-sc-conn"><span class="dot ok"></span>Connected</div>'
        '</div>'
        '<div class="nk-sc nk-sc-s">'
        '<div class="nk-sc-l">Namespace</div>'
        f'<div class="nk-chip">{esc(selected_ns)}</div>'
        '</div>'
        '<div class="nk-sc nk-sc-p">'
        '<div class="nk-sc-l">Overall health</div>'
        f'<div class="nk-big">{good_n}<span> of {len(services)} healthy</span></div>'
        f'<div class="nk-bar"><i style="width:{pct}%;background:{bar_color}"></i></div>'
        f'<div class="nk-sc-row"><span><span class="dot ok"></span>Healthy</span><b>{good_n}</b></div>'
        f'<div class="nk-sc-row"><span><span class="dot bad"></span>Need attention</span><b>{bad_n}</b></div>'
        '</div>'
        '<div class="nk-sc nk-sc-o">'
        '<div class="nk-sc-l">How to use</div>'
        '<div class="nk-step"><b>1</b><span>Pick your role on the main page.</span></div>'
        '<div class="nk-step"><b>2</b><span>Developers / DevOps: open a pod to see its errors and who caused it.</span></div>'
        '<div class="nk-step"><b>3</b><span>Business team: ask a question in the chat.</span></div>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.toggle("Light theme", key="light")

# Landing choice. The chat input only pins to the bottom of the page when it is called at the
# top level (not inside a tab), so the two audiences are separate views, not st.tabs.
audience = st.query_params.get("role")
if audience not in ("dev", "business"):
    audience = None

ROLES = [
    ("dev", "dev", "Developers / DevOps", "01",
     ["Open a pod from the Pods by namespace list.",
      "Read the errors, the cause and who caused it.",
      "Use Claude’s take for a suggested fix."],
     '''<div class="nk-ico"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16"/></svg></div>'''),
    ("business", "biz", "Business team", "02",
     ["Click a suggested question, or type your own.",
      "Read the answer: ✅ is working, ❌ needs attention.",
      "For detailed questions, ask the engineering team."],
     '''<div class="nk-ico"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg></div>'''),
]
if audience is None:
    st.markdown('<div class="nk-hero-s">Who are you?</div>', unsafe_allow_html=True)
# Before a choice both boxes show; after a click only the chosen box stays, plus a "Change role" button.
# Each box is a link: clicking anywhere on it opens that view (?role=...).
shown = ROLES if audience is None else []  # once a role is chosen, the boxes are hidden; only "Change role" stays
for col, (key, cls, title, num, desc, ico) in zip(st.columns(2), shown):
    sel_cls = " sel" if audience == key else ""
    compact = " compact" if audience else ""
    with col:
        st.markdown(
            f'<div class="nk-role {cls}{sel_cls}{compact}">'
            f'<a class="nk-cover" href="?role={key}" target="_self" aria-label="Open {esc(title)}"></a>'
            f'<div class="nk-rhead">{ico}<div class="nk-role-t">{title}</div><div class="nk-num2">{num}</div></div>'
            '<div class="nk-role-steps"><div class="nk-howto">How to use</div>'
            + "".join(f'<div class="nk-rstep"><b>{k}</b><span>{esc(line)}</span></div>' for k, line in enumerate(desc, 1))
            + '</div></div>',
            unsafe_allow_html=True,
        )
if audience is None:
    st.stop()
if st.button("⇄ Change role", key="aud-back"):
    st.query_params.clear()
    st.rerun()

view = "Pod details" if audience == "dev" else "Ask Devops-Konnekt"

crashing_pods = [s for s in services if not s["healthy"]]
healthy_n = len(services) - len(crashing_pods)

hour = datetime.now().hour
greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
today = datetime.now().strftime("%a, %b %d").replace(" 0", " ")
sub = "Check service health, investigate issues and find the cause."

st.markdown(
    f'<div class="nk-top">{mark("warn" if crashing_pods else "ok")}<div class="nk-title">{greeting}</div></div>'
    f'<div class="nk-sub">{esc(today)}. {esc(sub)}</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="nk-tiles">'
    f'<div class="nk-tile"><div class="nk-num" style="color:var(--green)">{healthy_n}</div><div class="nk-lbl">Healthy</div></div>'
    f'<div class="nk-tile"><div class="nk-num" style="color:{"var(--champagne)" if crashing_pods else "var(--text)"}">{len(crashing_pods)}</div><div class="nk-lbl">Need attention</div></div>'
    f'<div class="nk-tile"><div class="nk-num">{len(services)}</div><div class="nk-lbl">Pods in {esc(selected_ns)}</div></div>'
    '</div>',
    unsafe_allow_html=True,
)

if view == "Pod details":
    sel = next((s for s in services if s["pod_name"] == st.session_state.get("selected")), None)
    if sel:
        if st.button("← All pods", key="back-pods"):
            st.session_state["selected"] = None
            st.rerun()
        st.markdown('<div style="height:14px"></div>', unsafe_allow_html=True)
        render_pod(sel, selected_ns)
    else:
        # Pod list first, grouped by namespace; details only after a click.
        def open_pod(ns: str, pod: str) -> None:
            st.session_state["ns"] = ns
            st.session_state["selected"] = pod

        with st.container(key="podsection", gap="xxsmall"):
            st.markdown('<div class="nk-h">Pods by namespace</div>', unsafe_allow_html=True)
            # Read every namespace first, then stack the boxes into three columns, always adding to the
            # shortest one, so short boxes don't leave empty space under them (like a masonry layout).
            show_sys = st.toggle("Show system namespaces", key="show_sys")
            visible = [ns for ns in namespaces if show_sys or not is_system_namespace(ns)]
            hidden_n = len(namespaces) - len(visible)
            if hidden_n:
                st.caption(f"{hidden_n} system namespace(s) hidden.")
            loaded = []
            for i, ns in enumerate(visible):
                try:
                    loaded.append((i, ns, services if ns == selected_ns else cached_state(ns)))
                except Exception:
                    loaded.append((i, ns, None))
            columns = st.columns(3, gap="xxsmall")
            heights = [0, 0, 0]
            for i, ns, ns_pods in loaded:
                j = heights.index(min(heights))
                heights[j] += 2 + (len(ns_pods) if ns_pods else 1)
                tone = "tspo"[i % 4]  # cycle teal / sky / pink / orange boxes
                with columns[j], st.container(border=False, key=f"nsbox-{tone}-{ns}", gap="xxsmall"):
                    if ns_pods is None:
                        st.markdown(f'<div class="nk-name">{esc(ns)}</div>', unsafe_allow_html=True)
                        st.caption("Could not read pods in this namespace.")
                        continue
                    st.markdown(
                        f'<div class="nk-name" style="font-size:15px">{esc(ns)} <span class="nk-k">({len(ns_pods)})</span></div>',
                        unsafe_allow_html=True,
                    )
                    if not ns_pods:
                        st.caption("No pods.")
                    for p in ns_pods:
                        dot = ":green[●]" if p["healthy"] else ":red[●]"
                        st.button(
                            f"•  {p['pod_name']}  {dot} {p['state']}",
                            key=f"main-pod-{ns}-{p['pod_name']}",
                            type="tertiary",
                            on_click=open_pod,
                            args=(ns, p["pod_name"]),
                        )
            st.caption("Click a pod to see its details.")
else:
    if "messages" not in st.session_state:
        st.session_state.messages = [{
            "role": "assistant",
            "content": "Hi, I'm Devops-Konnekt. Ask me simple questions about your services: what is working, what is not, and whether anything had a problem.",
        }]
    cols = st.columns(len(SAMPLE_PROMPTS))
    for col, sp in zip(cols, SAMPLE_PROMPTS):
        if col.button(sp, key=f"sp-{sp}", use_container_width=True):
            st.session_state["pending"] = sp

    # Order on the page: chat messages, then the input bar, then Claude's take.
    # The input bar sits inside a container, so it stays in the page flow (it is not pinned to the window)
    # and Claude's take can be placed below it.
    thread = st.container()
    with thread:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg["role"] == "assistant":
                    copy_button(msg["content"])

    with st.container():
        prompt = st.chat_input("Ask about your services: what is working, what is not, whether anything had a problem") or st.session_state.pop("pending", None)

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        reply = generate_reply(prompt, services, selected_ns)
        st.session_state.messages.append({"role": "assistant", "content": reply})
        with thread:
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                st.markdown(reply)
                copy_button(reply)

    # Questions the app cannot answer itself can go to Claude, after the user sees exactly what is sent.
    with thread:
        last = st.session_state.messages[-1]
        if last["role"] == "assistant" and last["content"] == COMPLEX_REPLY and llm.backend():
            question = next((m["content"] for m in reversed(st.session_state.messages) if m["role"] == "user"), None)
            if question:
                if st.button("Ask Claude about this", key="biz-ask"):
                    st.session_state["biz_preview"] = True
                if st.session_state.get("biz_preview"):
                    ctx, report = build_business_context(services, selected_ns)
                    q = masking.mask_text(question)
                    with st.container(border=True):
                        st.markdown("**This is exactly what will be sent to Claude**")
                        st.caption("Service names, states and restart counts only. No logs.")
                        st.code(f"{ctx}\n\nQuestion: {q}", language="text")
                        a, b = st.columns(2)
                        go = a.button("Approve and send", key="biz-go", type="primary", use_container_width=True)
                        cancel = b.button("Cancel", key="biz-cancel", use_container_width=True)
                    if cancel:
                        st.session_state.pop("biz_preview", None)
                        st.rerun()
                    if go:
                        st.session_state.pop("biz_preview", None)
                        with st.spinner("Claude is thinking..."):
                            res = llm.business_chat(ctx, q)
                        if "text" in res:
                            st.session_state.messages.append(
                                {"role": "assistant", "content": res["text"] + "\n\n*Answered by Claude from the service status above.*"}
                            )
                            st.rerun()
                        else:
                            st.error(res["error"])

    if services:
        render_business_claude_take(services, selected_ns)
