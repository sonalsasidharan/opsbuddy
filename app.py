import os
import re
from datetime import datetime, timezone

import streamlit as st
from kubernetes import client, config

import gitinfo
import llm
import masking
from theme import CSS, esc, inline, mark

st.set_page_config(page_title="Devops-Konnekt", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)


# --- Connect to Kubernetes (~/.kube/config) ---
@st.cache_resource
def get_k8s_clients():
    # Point OPSBUDDY_KUBECONFIG at a read-only kubeconfig (see rbac.yaml) instead of your admin one.
    config.load_kube_config(config_file=os.environ.get("OPSBUDDY_KUBECONFIG") or None)
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


def generate_reply(user_prompt: str, cluster_state: list, namespace: str) -> str:
    q = user_prompt.lower()
    crashing = [p for p in cluster_state if not p["healthy"]]
    running = [p for p in cluster_state if p["state"] == "Running"]

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
            f"- **Running and healthy:** `{len(running)}`\n"
            f"- **Needs attention:** `{len(crashing)}`"
        )

    # 4. Stakeholder / Marketing / General Status Check
    if any(w in q for w in ["launch", "campaign", "marketing", "healthy", "status", "ready", "incident", "pod"]) or re.search(r"\bup\b", q):
        if not cluster_state:
            return f"No pods are deployed in `{namespace}`."
        if not crashing:
            lines = [f"**Everything in `{namespace}` is healthy. You're clear to launch.**\n"]
            for p in cluster_state:
                lines.append(f"- **{p['business_name']}** (`{p['pod_name']}`): healthy, `{p['restarts']}` restarts")
            return "\n".join(lines)
        lines = [f"**Hold the launch. {len(crashing)} service(s) need attention.**\n"]
        for p in cluster_state:
            status_text = "operational" if p["healthy"] else f"degraded ({p['state']}, {p['restarts']} restarts)"
            lines.append(f"- **{p['business_name']}** (`{p['pod_name']}`): {status_text}")
        lines.append("\nAsk *\"Show top 10 error lines\"*, *\"Show warning events\"* or *\"Who caused it?\"*.")
        return "\n".join(lines)

    # 5. Help / Fallback
    return (
        "I can help stakeholders, developers and DevOps. Try:\n"
        "- **Marketing and PMs:** *\"Is everything healthy for our launch?\"*\n"
        "- **Developers:** *\"Top 10 error lines for payment-service\"*\n"
        "- **DevOps:** *\"Show warning events and resource limits\"*\n"
        "- **Everyone:** *\"Who caused the crash?\"*"
    )




# ---------------- UI ----------------
SAMPLE_PROMPTS = [
    "Is everything healthy for launch?",
    "Who caused the crash?",
    "How do I fix payment-service?",
    "Show warning events and resource limits",
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


def render_log_search(pod: dict, namespace: str):
    st.markdown('<div class="nk-h">Search logs</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="nk-note" style="margin:-4px 0 10px 0">Reads straight from Kubernetes. Nothing is sent to Claude. '
        'Secrets are masked in what you see.</div>',
        unsafe_allow_html=True,
    )
    pid = pod["pod_name"]
    c1, c2 = st.columns([3, 2])
    keyword = c1.text_input("Keyword", key=f"kw-{pid}", placeholder="timeout, user 4821, connection refused")
    source = c2.selectbox(
        "Which run", ["Current container", "Before the last restart"],
        index=1 if pod["restarts"] > 0 and not pod["healthy"] else 0, key=f"src-{pid}",
    )
    c3, c4 = st.columns([3, 2])
    window = c3.selectbox("Time", list(LOG_WINDOWS), index=2, key=f"win-{pid}")
    levels = c4.multiselect("Level", list(LEVEL_PATTERNS), key=f"lvl-{pid}", placeholder="Any")
    o1, o2 = st.columns(2)
    use_regex = o1.checkbox("Regular expression", key=f"rx-{pid}")
    case = o2.checkbox("Match case", key=f"cs-{pid}")

    start = end = None
    since = LOG_WINDOWS[window]
    if since == "custom":
        now = datetime.now(timezone.utc)
        d1, t1, d2, t2 = st.columns(4)
        fd = d1.date_input("From date", value=now.date(), key=f"fd-{pid}")
        ft = t1.time_input("From time", value=(now.replace(hour=0, minute=0)).time(), key=f"ft-{pid}")
        td = d2.date_input("To date", value=now.date(), key=f"td-{pid}")
        tt = t2.time_input("To time", value=now.time().replace(second=0, microsecond=0), key=f"tt-{pid}")
        start = datetime.combine(fd, ft, tzinfo=timezone.utc)
        end = datetime.combine(td, tt, tzinfo=timezone.utc).replace(second=59)
        if end < start:
            st.warning("The end of the range is before the start.")
            return
        since = max(60, int((now - start).total_seconds()) + 1)  # let the API trim the start side

    prev = source != "Current container"
    res = fetch_log_lines(pid, namespace, prev, since)
    if prev and not res.get("lines"):
        # Kubernetes often can't return the previous run's logs for a pod that is crash-looping.
        st.caption("Kubernetes has no logs for the previous run right now, so this shows the current container.")
        res = fetch_log_lines(pid, namespace, False, since)
    if "error" in res:
        st.info(res["error"])
        return
    total = len(res["lines"])
    matches, err = filter_log_lines(res["lines"], keyword.strip(), use_regex, case, levels, start, end)
    if err:
        st.warning(err)
        return
    if not total:
        st.info("No log lines in this window. Try a longer time range, or the other run.")
        return
    shown = matches[-LOG_VIEW_CAP:]
    note = f"{len(matches)} of {total} lines match."
    if len(matches) > LOG_VIEW_CAP:
        note += f" Showing the latest {LOG_VIEW_CAP}; download for all of them."
    if total >= 5000:
        note += " Only the latest 5,000 lines are read, so older lines may be missing."
    st.caption(note + " Times are UTC.")
    if matches:
        masked = masking.mask_text("\n".join(matches))
        st.code(masking.mask_text("\n".join(shown)), language="text")
        st.download_button("Download matches", masked, file_name=f"{pid}-logs.txt", key=f"dl-{pid}")
    else:
        st.info("Nothing matches those filters.")


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
        render_log_search(pod, namespace)
        return

    logs = get_top_errors(pod["pod_name"], namespace, lines=10)
    summary, hint = explain_root_cause(logs, pod["state"])
    ci = commit_for_pod(pod)

    st.markdown('<div class="nk-h">What went wrong</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="nk-card"><div class="nk-line" style="margin-top:0">{inline(summary)}</div>'
        f'<div class="nk-line"><span class="nk-k">What to check.</span> {inline(hint)}</div></div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="nk-h">Who caused it</div>', unsafe_allow_html=True)
    st.markdown(commit_card(ci), unsafe_allow_html=True)

    st.markdown('<div class="nk-h">Error log lines</div>', unsafe_allow_html=True)
    st.code(logs, language="text")
    ev = get_pod_events(namespace, pod["pod_name"].split("-")[0], pod.get("uid"))
    if ev:
        with st.expander("Kubernetes warning events"):
            st.markdown("\n".join(ev))

    render_log_search(pod, namespace)

    st.markdown('<div class="nk-h">Claude’s take</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="nk-note" style="margin:-4px 0 10px 0">Sends this pod’s state, the error lines above (secrets masked), '
        'warning events and the suspect commit’s author and message to Claude. You see exactly what will be sent and approve it first.</div>',
        unsafe_allow_html=True,
    )
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
    if error:
        st.error(error)


# --- Sidebar: namespace and the pod list with health ---
with st.sidebar:
    st.markdown('<div class="nk-name" style="font-size:18px;margin-bottom:14px">Devops-Konnekt</div>', unsafe_allow_html=True)
    namespaces = get_namespaces()
    default_idx = namespaces.index("demo-apps") if "demo-apps" in namespaces else 0
    selected_ns = st.selectbox("Namespace", namespaces, index=default_idx)
    if st.button("Refresh", use_container_width=True):
        st.rerun()

    services = fetch_cluster_state(selected_ns)
    names = [s["pod_name"] for s in services]
    if st.session_state.get("selected") not in names:
        failing = [s["pod_name"] for s in services if not s["healthy"]]
        st.session_state["selected"] = (failing or names or [None])[0]

    st.markdown('<div class="nk-h" style="font-size:15px">Pods</div>', unsafe_allow_html=True)
    if not services:
        st.caption(f"No pods in {selected_ns}.")
    for s in services:
        dot = ":green[●]" if s["healthy"] else ":red[●]"
        is_sel = s["pod_name"] == st.session_state["selected"]
        if st.button(
            f"{dot}  {s['business_name']} ({s['state']})",
            key=f"pod-{s['pod_name']}",
            type="primary" if is_sel else "secondary",
            use_container_width=True,
        ):
            st.session_state["selected"] = s["pod_name"]
            st.rerun()

    notes = [
        "GitHub token set." if gitinfo.has_token() else "No GitHub token: public repos only, 60 lookups an hour.",
        {"api": "Claude: using your API key.", "claude-code": "Claude: using your Claude Code login, no API key needed.",
         None: "Claude analysis is off: install Claude Code or set ANTHROPIC_API_KEY."}[llm.backend()],
    ]
    st.markdown(
        '<div class="nk-note" style="margin-top:22px">' + "<br>".join(esc(n) for n in notes) + "</div>",
        unsafe_allow_html=True,
    )

crashing_pods = [s for s in services if not s["healthy"]]
healthy_n = len(services) - len(crashing_pods)

hour = datetime.now().hour
greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
today = datetime.now().strftime("%a, %b %d").replace(" 0", " ")
if not services:
    sub = f"Nothing is running in {selected_ns} yet."
elif crashing_pods:
    n = len(crashing_pods)
    sub = f"{n} {'service needs' if n == 1 else 'services need'} you in {selected_ns}."
else:
    sub = f"You're up to date. Everything in {selected_ns} is healthy."

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

tab_pod, tab_chat = st.tabs(["Pod details", "Ask Devops-Konnekt"])

with tab_pod:
    sel = next((s for s in services if s["pod_name"] == st.session_state.get("selected")), None)
    if sel:
        st.markdown('<div style="height:14px"></div>', unsafe_allow_html=True)
        render_pod(sel, selected_ns)
    else:
        st.info("Choose a pod from the list on the left.")

with tab_chat:
    if "messages" not in st.session_state:
        st.session_state.messages = [{
            "role": "assistant",
            "content": "Hi, I'm Devops-Konnekt. Ask about launch readiness, errors, events, who caused a crash, or how to fix it.",
        }]
    cols = st.columns(len(SAMPLE_PROMPTS))
    for col, sp in zip(cols, SAMPLE_PROMPTS):
        if col.button(sp, key=f"sp-{sp}", use_container_width=True):
            st.session_state["pending"] = sp

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    prompt = st.chat_input("Ask about launch status, errors, events, who caused a crash, or how to fix it") or st.session_state.pop("pending", None)
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        reply = generate_reply(prompt, services, selected_ns)
        st.session_state.messages.append({"role": "assistant", "content": reply})
        with st.chat_message("assistant"):
            st.markdown(reply)
