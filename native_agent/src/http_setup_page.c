#include "http_setup_page.h"
#include "http_util.h"

#include <string.h>

void c300x_http_setup_page(int client_fd)
{
    static const char header[] =
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n"
        "\r\n";
    static const char *parts[] = {
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>C300X Agent Setup</title><style>body{font-family:system-ui,sans-serif;background:#111;color:#eee;margin:0}"
        "main{max-width:900px;margin:auto;padding:20px;min-width:0}section{border:1px solid #333;border-radius:8px;padding:14px;margin:0 0 14px;background:#181818;min-width:0}"
        "label{display:block;margin-top:8px;color:#bbb}input,select,textarea{box-sizing:border-box;width:100%;padding:7px;background:#0b0b0b;color:#eee;border:1px solid #444;border-radius:4px}"
        "button{margin:8px 8px 0 0;padding:8px 12px;border:0;border-radius:4px;background:#326de6;color:#fff}.g{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;min-width:0}"
        ".opt{display:grid;grid-template-columns:minmax(170px,220px) 1fr;gap:10px;align-items:start;margin-top:8px}.opt span{color:#ddd}.opt input{width:auto;margin-right:6px}.opt small{color:#9ca3af;line-height:1.35}"
        "pre{white-space:pre-wrap;background:#080808;border:1px solid #333;border-radius:4px;padding:10px;max-height:42vh;overflow:auto;overflow-wrap:anywhere;word-break:break-word;font-size:12px;line-height:1.35}</style></head>",
        "<body><main><h1>C300X Agent Setup</h1><section><h2>Auth</h2><div id=\"as\">Not loaded</div><div class=\"g\"><div><label>API token for requests</label><input id=\"ah\" type=\"text\" autocomplete=\"off\" spellcheck=\"false\" placeholder=\"enter token if configured\"></div>"
        "<div><label>Maintenance token for requests</label><input id=\"mh\" type=\"text\" autocomplete=\"off\" spellcheck=\"false\" placeholder=\"enter token if configured\"></div><div><label>New API token</label><input id=\"at\" type=\"text\" autocomplete=\"new-password\" spellcheck=\"false\"></div>"
        "<div><label>New maintenance token</label><input id=\"mt\" type=\"text\" autocomplete=\"off\" spellcheck=\"false\"></div></div><label class=\"opt\"><span><input id=\"na\" type=\"checkbox\"> noAuth</span><small>Allows temporary setup without Bearer auth. Disable it after tokens are saved.</small></label>",
        "<button onclick=\"load()\">Load</button><button onclick=\"save()\">Save</button></section><section><h2>Config</h2><div class=\"g\">"
        "<div><label>API listen host</label><input id=\"lh\"></div><div><label>API port</label><input id=\"ap\" type=\"number\"></div>"
        "<div><label>Internal UI port</label><input id=\"up\" type=\"number\"></div><div><label>UI bind</label><input id=\"ub\" value=\"127.0.0.1 only\" readonly></div>"
        "<div><label>Stair light</label><input id=\"sa\"></div></div>"
        "<label class=\"opt\"><span><input id=\"lan\" type=\"checkbox\"> allow LAN for API</span><small>Lets HA reach the API on the configured host. The internal UI listener stays on localhost.</small></label>"
        "<label class=\"opt\"><span><input id=\"vid\" type=\"checkbox\"> video</span><small>Enables the doorbell SIP/RTSP video bridge. Media starts only when requested.</small></label>"
        "<label class=\"opt\"><span><input id=\"db\" type=\"checkbox\"> display bridge</span><small>Enables the local QML bridge for the HA dashboard and alarm page.</small></label>"
        "<label class=\"opt\"><span><input id=\"ev\" type=\"checkbox\"> events</span><small>Listens for device events and forwards only subscribed event types to HA.</small></label>"
        "<label class=\"opt\"><span><input id=\"mm\" type=\"checkbox\"> memos</span><small>Exposes text and voice memos, including delete support when the Display patch is active.</small></label>"
        "<label class=\"opt\"><span><input id=\"vm\" type=\"checkbox\"> video messages</span><small>Exposes answering-machine video messages for HA playback and deletion.</small></label>"
        "<label class=\"opt\"><span><input id=\"sm\" type=\"checkbox\"> system metrics</span><small>Publishes CPU, memory, load, and temperature only when HA subscribes to metric events.</small></label>"
        "<label class=\"opt\"><span><input id=\"me\" type=\"checkbox\"> maintenance</span><small>Allows protected maintenance endpoints such as SSH, reboot, Display reload, Display patch, and firewall.</small></label>"
        "<label class=\"opt\"><span><input id=\"mn\" type=\"checkbox\"> allow noAuth maintenance</span><small>Allows maintenance calls without the maintenance token while noAuth is enabled. Keep this temporary.</small></label>"
        "<label class=\"opt\"><span><input id=\"md\" type=\"checkbox\"> mDNS discovery until HA connects</span><small>Advertises the agent on the local network only while HA is not connected.</small></label>"
        "<label class=\"opt\"><span><input id=\"fw\" type=\"checkbox\"> firewall maintenance</span><small>Allows IPv4 firewall status/apply/restore. Saving this option does not change firewall rules.</small></label>"
        "<label class=\"opt\"><span><input id=\"fw6\" type=\"checkbox\"> IPv6 firewall maintenance</span><small>Allows IPv6 ICMP and API-port rules through ip6tables in the persistent network script.</small></label><button onclick=\"save()\">Save config</button></section>",
        "<section><h2>Manual API</h2><div class=\"g\"><div><label>Endpoint</label><select id=\"ep\" onchange=\"pick()\">",
        "<option value=\"GET /api/v1/health\">GET health</option><option value=\"GET /api/v1/capabilities\">GET capabilities</option>"
        "<option value=\"GET /api/v1/state\">GET state</option><option value=\"GET /api/v1/display-bridge\">GET display bridge</option>"
        "<option value=\"POST /api/v1/display-bridge\">POST display bridge</option><option value=\"GET /api/v1/events/recent\">GET recent events</option>"
        "<option value=\"GET /api/v1/events/subscriptions\">GET event subscriptions</option><option value=\"POST /api/v1/events/subscriptions\">POST event subscription</option>"
        "<option value=\"DELETE /api/v1/events/subscriptions/{id}\">DELETE event subscription</option><option value=\"GET /api/v1/system/metrics\">GET system metrics</option>"
        "<option value=\"GET /api/v1/diagnostics\">GET diagnostics</option><option value=\"GET /api/v1/maintenance/auth\">GET auth config</option>",
        "<option value=\"POST /api/v1/maintenance/auth\">POST auth config</option><option value=\"POST /api/v1/stair-light/actions/activate\">POST stair light</option>"
        "<option value=\"GET /api/v1/smartphone-forwarding\">GET smartphone forwarding</option><option value=\"POST /api/v1/smartphone-forwarding\">POST smartphone forwarding</option>"
        "<option value=\"GET /api/v1/ringer\">GET ringer</option><option value=\"POST /api/v1/ringer\">POST ringer</option>"
        "<option value=\"GET /api/v1/video/doorbell\">GET doorbell video</option><option value=\"GET /api/v1/video/doorbell/status\">GET doorbell video status</option><option value=\"POST /api/v1/video/doorbell/actions/activate\">POST activate doorbell video</option>"
        "<option value=\"POST /api/v1/video/doorbell/actions/stop\">POST stop doorbell video</option><option value=\"GET /api/v1/calls/home\">GET home call</option><option value=\"POST /api/v1/calls/home/actions/start\">POST start home call</option>"
        "<option value=\"POST /api/v1/calls/home/actions/stop\">POST stop home call</option><option value=\"GET /api/v1/answering-machine\">GET answering machine</option>"
        "<option value=\"POST /api/v1/answering-machine\">POST answering machine</option><option value=\"GET /api/v1/answering-machine/messages\">GET video messages</option>",
        "<option value=\"GET /api/v1/answering-machine/messages/{id}/video\">GET video message media</option><option value=\"POST /api/v1/answering-machine/messages/actions/delete\">POST delete video message</option>"
        "<option value=\"GET /api/v1/memos\">GET memos</option><option value=\"GET /api/v1/memos/voice/{id}/audio\">GET voice memo audio</option><option value=\"POST /api/v1/memos/actions/delete\">POST delete memo</option>"
        "<option value=\"POST /api/v1/locks/{id}/actions/unlock\">POST unlock lock by id</option><option value=\"POST /api/v1/locks/default/actions/unlock\">POST unlock default lock</option><option value=\"GET /api/v1/maintenance/ssh\">GET SSH status</option>"
        "<option value=\"POST /api/v1/maintenance/ssh\">POST SSH set</option><option value=\"POST /api/v1/maintenance/ssh/actions/start\">POST SSH start</option>"
        "<option value=\"POST /api/v1/maintenance/ssh/actions/stop\">POST SSH stop</option><option value=\"POST /api/v1/maintenance/reboot\">POST reboot</option>"
        "<option value=\"POST /api/v1/maintenance/agent/actions/remove\">POST remove agent</option>"
        "<option value=\"POST /api/v1/maintenance/agent/actions/restart\">POST restart agent</option>"
        "<option value=\"POST /api/v1/maintenance/gui/actions/reload\">POST reload display</option><option value=\"GET /api/v1/maintenance/firewall\">GET firewall status</option>"
        "<option value=\"POST /api/v1/maintenance/firewall/actions/apply\">POST apply firewall</option><option value=\"POST /api/v1/maintenance/firewall/actions/restore\">POST restore firewall</option>"
        "<option value=\"GET /api/v1/maintenance/ipv6-firewall\">GET IPv6 firewall status</option><option value=\"POST /api/v1/maintenance/ipv6-firewall/actions/apply\">POST apply IPv6 firewall</option><option value=\"POST /api/v1/maintenance/ipv6-firewall/actions/restore\">POST restore IPv6 firewall</option>"
        "<option value=\"GET /api/v1/maintenance/qml-patch\">GET Display patch status</option>"
        "<option value=\"POST /api/v1/maintenance/qml-patch/actions/apply-core\">POST apply core media hook</option>"
        "<option value=\"POST /api/v1/maintenance/qml-patch/actions/restore-core\">POST restore core media hook</option>"
        "<option value=\"POST /api/v1/maintenance/qml-patch/actions/apply\">POST apply Display patch</option><option value=\"POST /api/v1/maintenance/qml-patch/actions/restore\">POST restore Display patch</option>",
        "</select></div><div><label>Method</label><select id=\"m\"><option>GET</option><option>POST</option><option>DELETE</option></select></div>"
        "<div><label>Path</label><input id=\"p\" value=\"/api/v1/health\"></div></div><label>JSON body</label><textarea id=\"b\" rows=\"4\"></textarea>"
        "<button onclick=\"call()\">Send</button><button onclick=\"quick('/api/v1/capabilities')\">Capabilities</button><button onclick=\"quick('/api/v1/diagnostics')\">Diagnostics</button></section>",
        "<section><h2>Output</h2><pre id=\"o\"></pre></section><script>const $=i=>document.getElementById(i);"
        "function h(j=1){let x={};if(j)x['Content-Type']='application/json';if($('ah').value)x.Authorization='Bearer '+$('ah').value;if($('mh').value)x['X-Bticino-C300X-Maintenance-Token']=$('mh').value;return x}"
        "function out(q,t){let s=t;try{s=JSON.stringify(JSON.parse(t),null,2)}catch(e){}$('o').textContent=q.status+' '+q.statusText+'\\n'+s}async function r(m,p,b){let q=await fetch(p,{method:m,headers:h(b!==undefined),body:b===undefined?undefined:JSON.stringify(b)}),t=await q.text();out(q,t);try{return JSON.parse(t)}catch(e){return null}}"
        "function yn(v,f){return v?'configured '+(f||''):'missing'}function put(d){if(!d)return;$('as').textContent='noAuth: '+(d.noAuth?'on':'off')+' | API token: '+yn(d.api_token_configured,d.api_token_fingerprint)+' | Maintenance token: '+yn(d.maintenance_token_configured,d.maintenance_token_fingerprint);$('na').checked=!!d.noAuth;$('lh').value=d.listen_host||'';$('ap').value=d.api_port||'';$('up').value=d.ui_port||'';$('ub').value=(d.ui_listen_host||'127.0.0.1')+' only';$('sa').value=d.stair_light_default_address||'';for(let k of [['lan','allow_lan'],['vid','video_enabled'],['db','display_bridge_enabled'],['ev','events_enabled'],['mm','memos_enabled'],['vm','video_messages_enabled'],['sm','system_metrics_enabled'],['me','maintenance_enabled'],['mn','maintenance_no_auth_allowed'],['md','mdns_enabled'],['fw','firewall_enabled'],['fw6','ipv6_firewall_enabled']])$(k[0]).checked=!!d[k[1]]}"
        "async function load(){put(await r('GET','/api/v1/maintenance/auth'))}async function save(){let b={setupComplete:true,noAuth:$('na').checked,listenHost:$('lh').value,apiPort:+$('ap').value,uiPort:+$('up').value,stairLightDefaultAddress:$('sa').value,allowLan:$('lan').checked,videoEnabled:$('vid').checked,displayBridgeEnabled:$('db').checked,eventsEnabled:$('ev').checked,memosEnabled:$('mm').checked,videoMessagesEnabled:$('vm').checked,systemMetricsEnabled:$('sm').checked,maintenanceEnabled:$('me').checked,maintenanceNoAuthAllowed:$('mn').checked,mdnsEnabled:$('md').checked,firewallEnabled:$('fw').checked,ipv6FirewallEnabled:$('fw6').checked};if($('at').value)b.apiToken=$('at').value;if($('mt').value)b.maintenanceToken=$('mt').value;let d=await r('POST','/api/v1/maintenance/auth',b);if(d&&d.ok){if($('at').value)$('ah').value=$('at').value;if($('mt').value)$('mh').value=$('mt').value}$('at').value='';$('mt').value='';put(d)}"
        "function pick(){let v=$('ep').value,i=v.indexOf(' ');$('m').value=v.slice(0,i);$('p').value=v.slice(i+1);$('b').value=''}async function call(){let x=$('b').value.trim(),b=x?JSON.parse(x):undefined;await r($('m').value,$('p').value,b)}function quick(p){$('m').value='GET';$('p').value=p;$('b').value='';call()}pick();load()</script></main></body></html>",
        NULL
    };

    if (!c300x_http_write(client_fd, header, strlen(header))) {
        return;
    }
    for (size_t index = 0; parts[index] != NULL; index++) {
        if (!c300x_http_write(client_fd, parts[index], strlen(parts[index]))) {
            return;
        }
    }
}
