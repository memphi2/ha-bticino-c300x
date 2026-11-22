# Sourced by the display transaction. Only the fixed loopback API is contacted.
probe_runtime() {
    probe_generation=$1
    probe_mode=${2:-ready}
    safe_path "$AGENT/c300x-agent-native" && regular "$AGENT/c300x-agent-native" || return 1
    # Never inherit a proxy that could route the loopback check off the device.
    unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY
    probe_url="http://127.0.0.1:8090/ui/c100x/presence"
    probe_token=$(wget -q -Y off -T 2 -O - --header='X-C100X-GUI: presence-v1' \
        "$probe_url/probe?generation=$probe_generation" \
        | "$AGENT/c300x-agent-native" --c100x-gui-response challenge - -) || return 1
    # The GUI replies by opening a new guarded sleeping request. Four bounded
    # reads only; the agent rejects responses after its two-second challenge.
    probe_attempt=0
    while [ "$probe_attempt" -lt 4 ]; do
        if wget -q -Y off -T 2 -O - --header='X-C100X-GUI: presence-v1' \
            "$probe_url/status?generation=$probe_generation&probe=$probe_token" \
            | "$AGENT/c300x-agent-native" --c100x-gui-response "$probe_mode" "$probe_generation" "$probe_token"; then
            return 0
        fi
        probe_attempt=$((probe_attempt + 1))
        sleep 0.25
    done
    return 1
}
