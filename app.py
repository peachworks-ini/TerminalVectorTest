import http.server
import json
import math
import socketserver
import threading
import time

PORT = 8080
PROGRAM_START_TIMES = {"ACA7246": 1 * 3600 + 34 * 60 + 23, "DLH456": 4 * 3600 + 5 * 60 + 12}

# Pre-loaded Demo Scenarios with Catbox Video Links
FALLBACK_MOCK_PLANES = [
    {
        "flight": "ACA7246", "hex": "C-FKSV", "type": "Boeing 787-9", "desc": "Air Canada",
        "route": "LAX -> YYZ", "alt_baro": 0, "gs": 45, "vertical_speed": 0, "track": 250,
        "status": "DEPARTING 25R", "dist": 0.0,
        "video": "https://files.catbox.moe/u5tvpm.mp4"
    },
    {
        "flight": "DLH456", "hex": "D-ABYT", "type": "Boeing 747-8i", "desc": "Lufthansa",
        "route": "FRA -> LAX", "alt_baro": 400, "gs": 149, "vertical_speed": -500, "track": 240,
        "status": "LANDING 24R", "dist": 3.2,
        "video": "https://files.catbox.moe/e8rezn.mp4"
    },

]

# Aircraft tag coordinates in the original 1920x1080 video canvas. Times are seconds from playback start.
TRACK_COORDS = {
    "ACA7246": [
        (0, 581, 260), (9, 581, 260), (9.05, 470, 268), (16, 470, 268),
        (17, 504, 314), (20, 504, 314), (27, 949, 308),
        (27.05, -183, 222), (39, 390, 293),
    ],
    "DLH456": [
        (0,891,518),(1,937,542),(2,933,550),(3,943,551),(4,943,562),(5,938,549),
        (6,954,546),(7,941,545),(8,937,547),(9,925,577),(10,930,570),(11,940,567),
        (12,935,566),(13,933,577),(14,947,564),(15,945,567),(16,938,561),(17,933,561),
        (18,937,560),(19,943,563),(20,918,565),(21,924,562),(22,938,573),(23,950,577),
        (24,947,576),(25,977,571),(26,957,565),(27,954,579),(28,953,582),(29,938,581),
        (30,920,541),(31,873,545),(32,795,555),(33,716,540),(34,724,545),(35,665,551),
        (36,508,543),(37,459,521),(38,494,517),(39,480,520),(40,492,532),(41,600,544),
        (42,641,539),(43,689,549),(44,1006,537),(45,1496,536),(46,1800,584),(47,1805,536),
        (48,1771,539),
    ],
}
TRACK_CANVAS_WIDTH = 1920
TRACK_CANVAS_HEIGHT = 1080


def telemetry_at(flight, elapsed):
    """Return demo telemetry for a flight at its current clip time."""
    telemetry = dict(flight)
    if flight.get("flight") == "DLH456":
        approach_speed = 148 + round(math.cos(elapsed * 0.43))
        approach_vs = -450 - round(50 * math.sin(elapsed * 0.31))
        if elapsed < 27:
            telemetry.update(alt_baro=400, gs=approach_speed, vertical_speed=approach_vs, status="LANDING 24R")
        elif elapsed < 28:
            flare = elapsed - 27
            telemetry.update(alt_baro=400, gs=approach_speed,
                             vertical_speed=round(approach_vs * (1.0 - flare)), status="FLARE · 24R")
        else:
            rollout = min(1.0, max(0.0, (elapsed - 28) / 19.0))
            touchdown_speed = 148 + round(math.cos(28 * 0.43))
            speed = round(touchdown_speed + (80 - touchdown_speed) * rollout)
            status = "TOUCHDOWN 24R" if elapsed < 30 else ("ROLLOUT 24R" if elapsed < 47 else "ROLLOUT 80 KTS")
            telemetry.update(alt_baro=0, gs=speed, vertical_speed=0, status=status)
    return telemetry


def tracked_position(flight_id, elapsed):
    points = TRACK_COORDS.get(flight_id)
    if not points:
        return None
    if elapsed <= points[0][0]:
        return points[0][1], points[0][2]
    for left, right in zip(points, points[1:]):
        if elapsed <= right[0]:
            span = right[0] - left[0]
            ratio = 1.0 if span <= 0 else max(0.0, min(1.0, (elapsed - left[0]) / span))
            return (left[1] + (right[1] - left[1]) * ratio,
                    left[2] + (right[2] - left[2]) * ratio)
    return points[-1][1], points[-1][2]


# Shared State Vector Store
ACTIVE_TELEMETRY = {
    "overlay_visible": True,
    "hud_logo_visible": True,
    "hud_center_visible": True,
    "hud_time_visible": True,
    "ar_visible": True,
    "ar_x": 65,
    "ar_y": 35,
    "clip_started_at": time.time(),
    "program_time_base": PROGRAM_START_TIMES["ACA7246"],
    "ar_manual_override_until": 0,
    "chat_visible": False,
    "chat_data": {"user": "", "message": "", "amount": "", "is_superchat": False},
    "active_flight": FALLBACK_MOCK_PLANES[0],
    "queue": FALLBACK_MOCK_PLANES,
    "events": [],
    "featured_event_id": None,
    "demo_action": "",
    "alert_until": 0,
    "source_version": 1,
    "automation_override_until": 0,
    "clients": {"controller": 0, "obs": 0},
    "demo_click": {"id": "", "target": ""}
}

# --- 1. TERMINALVECTOR COMMAND DECK (Route: / ) ---
HTML_CONTROLLER = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TerminalVector | Control Room</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
<style>
:root{color-scheme:dark;--bg:#080d16;--panel:#101925;--raised:#162231;--line:#26374a;--muted:#91a0b3;--text:#eff5fa;--mint:#4ce0b3;--amber:#ffbf58;--blue:#68aaff;--red:#ff7184}*{box-sizing:border-box}body{margin:0;width:100vw;height:100vh;overflow:hidden;background:radial-gradient(ellipse at 50% -25%,#1b3140 0,transparent 55%),var(--bg);color:var(--text);font:14px 'DM Sans',sans-serif}.topbar{height:72px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 26px;background:rgba(8,13,22,.82);position:sticky;top:0;z-index:4;backdrop-filter:blur(16px)}.brand{display:flex;align-items:center;gap:12px}.mark{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,var(--mint),#49a9ff);display:grid;place-items:center;color:#06111a;font:bold 17px 'Space Grotesk'}.brand strong{font:700 16px 'Space Grotesk';letter-spacing:.06em}.brand small{display:block;color:var(--muted);font-size:10px;letter-spacing:.16em;margin-top:3px}.live{color:var(--mint);font-weight:700;font-size:12px;letter-spacing:.1em}.live i{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--mint);margin-right:8px;box-shadow:0 0 14px var(--mint)}.demo-banner{position:absolute;top:0;left:0;width:100%;height:22px;display:grid;place-items:center;background:#c63748;color:#fff;font-size:11px;font-weight:800;letter-spacing:.09em;text-transform:uppercase}.topbar{padding-top:20px}.live{font-variant-numeric:tabular-nums}main{width:100%;height:calc(100vh - 72px);min-height:0;padding:16px;overflow:hidden;margin:auto;display:grid;grid-template-columns:minmax(265px, .95fr) minmax(450px,1.8fr) minmax(325px,1.2fr);grid-template-rows:minmax(0,1fr) minmax(0,1fr);gap:14px}.panel{background:linear-gradient(155deg,rgba(20,31,45,.98),rgba(13,21,32,.98));border:1px solid var(--line);border-radius:14px;overflow:hidden;min-height:0;box-shadow:0 18px 48px #0002}.panel-head{height:56px;padding:0 17px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line)}.panel-head h2{margin:0;font:600 13px 'Space Grotesk';letter-spacing:.07em;text-transform:uppercase}.panel-head em{font:italic 11px 'DM Sans';color:var(--muted);letter-spacing:0;text-transform:none}.count{color:var(--muted);font-size:11px}.aircraft{grid-row:1/3;display:flex;flex-direction:column}.aircraft-list{padding:10px;overflow:auto;flex:1}.flight{width:100%;text-align:left;display:grid;grid-template-columns:1fr auto;gap:3px 10px;border:1px solid transparent;border-radius:10px;background:#121e2b;color:var(--text);padding:13px;margin-bottom:7px;cursor:pointer;transition:.18s}.flight:hover,.flight.active{border-color:#426a72;background:#172a35;transform:translateY(-1px)}.flight strong{font:700 15px 'Space Grotesk'}.flight .dist{color:var(--mint);font-size:11px;text-align:right}.flight .meta{font-size:11px;color:var(--muted)}.flight .route{grid-column:1/-1;color:#d1dce6;font-size:11px;margin-top:4px}.hud{grid-column:2/4;display:flex;flex-direction:column}.hud-content{padding:18px;display:grid;grid-template-columns:1fr 145px;align-items:center;gap:12px;flex:1}.third{height:118px;display:flex;overflow:hidden;border-radius:11px;border:1px solid #32465b;background:linear-gradient(105deg,#142339,#1b3045);box-shadow:0 14px 32px #0005;transition:.3s}.third.off{opacity:.22;filter:grayscale(1);transform:translateY(5px)}.logo{width:104px;flex:none;border-left:5px solid var(--amber);display:grid;place-content:center;text-align:center;background:#0d1825}.logo b{font:800 24px 'Space Grotesk'}.logo small{color:var(--amber);font-size:10px;letter-spacing:.12em}.flight-info{padding:0 22px;display:flex;align-items:center;justify-content:space-between;flex:1;min-width:0}.callout b{font:700 23px 'Space Grotesk';display:block}.callout span,.metric span{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.12em}.callout small{color:#c0ccda}.metrics{display:flex;gap:23px}.metric strong{display:block;margin-top:4px;font:600 15px 'Space Grotesk'}.clock{height:118px;border-radius:11px;background:linear-gradient(135deg,#ffca68,#ef9c37);color:#201508;display:grid;place-content:center;text-align:center}.clock small{font-size:10px;letter-spacing:.14em}.clock b{font:700 23px 'Space Grotesk';margin-top:5px}.hud-elements{display:flex;gap:7px;flex-wrap:wrap;padding:0 18px 15px}.element{border:1px solid var(--line);background:#111e2b;color:#bbc9d7;border-radius:7px;padding:7px 10px;cursor:pointer;font-size:11px}.element.on{border-color:#2e6a5d;color:var(--mint)}.lower{grid-column:2/3;display:flex;flex-direction:column}.chat{grid-column:3/4;display:flex;flex-direction:column}.chat-list{padding:12px 14px;overflow:auto;flex:1;display:flex;flex-direction:column;gap:7px}.chat-row{display:grid;grid-template-columns:52px 1fr;gap:8px;font-size:12px;line-height:1.4;padding:8px 9px;border-radius:8px;background:#121e2a;animation:in .25s ease}.chat-row .when{font-size:10px;color:#74869a;padding-top:2px}.chat-row strong{color:#9fc5ff}.chat-row.highlight{border:1px solid #547499;background:#172c3e;box-shadow:0 0 0 1px #68aaff55,0 0 12px #68aaff2e}.chat-row.superchat{border-left:3px solid var(--amber)}.chat-row.donation{border-left:3px solid #4cdda9}.chat-row.subscription{border-left:3px solid #c39aff}.recent-wrap{padding:12px;overflow:auto;flex:1}.recent-card{border:1px solid #344354;background:#141f2c;border-radius:10px;padding:15px;margin-bottom:8px;cursor:pointer;transition:.2s}.recent-card:hover,.recent-card.selected{border-color:var(--amber);background:#28271f;transform:translateY(-1px)}.recent-card b{display:block;font-size:13px}.recent-card span{display:block;color:var(--muted);font-size:11px;margin-top:6px}.tag{font-size:9px!important;text-transform:uppercase;letter-spacing:.1em;color:var(--amber)!important}.demo-note{color:var(--muted);font-size:10px;padding:0 14px 10px}@keyframes in{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}@keyframes pulse{50%{box-shadow:0 0 0 4px #4ce0b344}}.acting{animation:pulse .6s ease 2}.demo-pointer{position:fixed;z-index:20;left:-30px;top:-30px;width:19px;height:19px;border:2px solid #fff;border-radius:50%;background:#4ce0b3;box-shadow:0 0 0 3px #07131dcc,0 3px 12px #000;transform:translate(-50%,-50%);opacity:0;pointer-events:none;transition:left .55s cubic-bezier(.2,.8,.2,1),top .55s cubic-bezier(.2,.8,.2,1),opacity .15s}.demo-pointer.visible{opacity:1}.demo-pointer.click:after{content:"";position:absolute;inset:-7px;border:2px solid #4ce0b3;border-radius:50%;animation:clickRipple .55s ease-out}@keyframes clickRipple{to{inset:-22px;opacity:0}}@media(max-width:1050px){main{grid-template-columns:minmax(230px,.85fr) minmax(430px,1.4fr);grid-template-rows:390px 340px auto}.aircraft{grid-row:1/3}.hud{grid-column:2}.lower{grid-column:2}.chat{grid-column:1/3;min-height:300px}}@media(max-width:700px){main{display:flex;flex-direction:column;padding:12px}.aircraft{min-height:480px}.hud{min-height:280px}.lower,.chat{min-height:330px}.hud-content{grid-template-columns:1fr}.clock{height:65px}.third{height:108px}.metrics{gap:10px}.flight-info{padding:0 10px}.callout b{font-size:16px}.metric strong{font-size:12px}.topbar{padding:20px 14px 0}.demo-banner{font-size:9px;letter-spacing:.03em}}
</style></head><body><header class="topbar"><div class="brand"><div class="mark">TV</div><div><strong>TERMINALVECTOR</strong><small>BROADCAST CONTROL ROOM</small></div></div><div class="demo-banner">DEMO - Click Anywhere to Explore Features</div><div class="live"><i></i><span id="programTime">01:34:23</span></div></header>
<main>
<section class="panel aircraft"><div class="panel-head"><h2>Nearby Aircraft</h2><span class="count" id="aircraftCount">— targets</span></div><div class="aircraft-list" id="flightList"></div></section>
<section class="panel hud"><div class="panel-head"><h2>HUD Control <em>(tap to show / hide elements)</em></h2><span id="hudStatus" class="count">ON AIR</span></div><div class="hud-content"><div id="lowerThird" class="third"><div class="logo" id="previewLogo"><b>LA</b><small>FLIGHTS</small></div><div class="flight-info" id="previewCenter"><div class="callout"><b id="hudFlight">—</b><small id="hudMeta">—</small></div><div class="metrics"><div class="metric"><span>Altitude</span><strong id="hudAlt">—</strong></div><div class="metric"><span>Ground speed</span><strong id="hudSpeed">—</strong></div><div class="metric"><span>Vertical speed</span><strong id="hudVerticalSpeed">—</strong></div><div class="metric"><span>Status</span><strong id="hudFlightStatus">—</strong></div></div></div></div><div class="clock" id="previewTime"><small>LOCAL TIME</small><b id="clock">--:--</b></div></div><div class="hud-elements"><button class="element on" id="elLogo" onclick="toggleElement('logo')">◉ Logo</button><button class="element on" id="elCenter" onclick="toggleElement('center')">◉ Lower third info</button><button class="element on" id="elTime" onclick="toggleElement('time')">◷ Time</button><button class="element on" id="elTag" onclick="toggle('/api/toggle_ar')">◎ Aircraft tag</button></div></section>
<section class="panel lower"><div class="panel-head"><h2>Live Chat</h2><span class="count">SIMULATED · LAST 5 MIN</span></div><div class="chat-list" id="chatList"></div><div class="demo-note">Demo chat scrolls by in real time. Select a message to highlight it on program.</div></section>
<section class="panel chat"><div class="panel-head"><h2>Recent Super Chat / Donation</h2><span class="count">+ SUBSCRIPTIONS</span></div><div class="recent-wrap" id="recentList"></div><div class="demo-note">Click an alert to feature it on the program output.</div></section>
</main><div id="demoPointer" class="demo-pointer" aria-hidden="true"></div><script>
let state={},renderedFlight='',lastDemoClick='',renderedEventsKey='';const recentKinds=new Set(['superchat','donation','subscription']);
async function api(path,payload){return fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload||{})})}
function animateDemoClick(action){if(!action||!action.id||action.id===lastDemoClick)return;lastDemoClick=action.id;const target=document.getElementById(action.target);if(!target)return;target.scrollIntoView({block:'nearest',inline:'nearest',behavior:'smooth'});setTimeout(()=>{const r=target.getBoundingClientRect(),cursor=document.getElementById('demoPointer');cursor.classList.remove('click');cursor.style.left=(r.left+r.width/2)+'px';cursor.style.top=(r.top+r.height/2)+'px';cursor.classList.add('visible');setTimeout(()=>cursor.classList.add('click'),570);target.classList.remove('acting');void target.offsetWidth;target.classList.add('acting');setTimeout(()=>{cursor.classList.remove('click','visible')},1200)},180)}
async function heartbeat(){try{await api('/api/heartbeat',{client:'controller'})}catch(e){}}
document.addEventListener('pointerdown',()=>api('/api/override',{}));document.addEventListener('keydown',()=>api('/api/override',{}));
async function toggle(path){await api(path);await updateUI()}async function toggleElement(element){await api('/api/hud/element',{element});await updateUI()}
function clock(){document.getElementById('clock').textContent=new Date().toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'})}
function safe(s){const d=document.createElement('div');d.textContent=s||'';return d.innerHTML}
function formatTime(ts){return new Date(ts*1000).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'})}
async function selectFlight(f){await api('/api/select',{flight:f.flight});await updateUI()}
async function featureEvent(e){await api('/api/feature',{id:e.id});await updateUI()}
function renderEvents(events){const signature=events.map(e=>e.id+(e.highlighted?'!':'')).join('|');if(signature===renderedEventsKey)return;renderedEventsKey=signature;const chats=document.getElementById('chatList'),wasNearBottom=chats.scrollHeight-chats.scrollTop-chats.clientHeight<36;chats.innerHTML='';events.filter(e=>e.kind==='chat').slice(-60).forEach(e=>{const row=document.createElement('div');row.id='chat-'+e.id;row.className='chat-row'+(e.highlighted?' highlight':'');row.innerHTML=`<span class="when">${formatTime(e.ts)}</span><div><strong>${safe(e.user)}</strong> ${safe(e.text)}</div>`;row.onclick=()=>featureEvent(e);chats.appendChild(row)});if(wasNearBottom)chats.scrollTop=chats.scrollHeight;const recent=document.getElementById('recentList');recent.innerHTML='';events.filter(e=>recentKinds.has(e.kind)).slice(-6).reverse().forEach(e=>{const card=document.createElement('div');card.id='alert-'+e.id;card.className='recent-card'+(e.highlighted?' selected':'');const label={superchat:'SUPER CHAT',donation:'DONATION',subscription:'NEW SUBSCRIPTION'}[e.kind];card.innerHTML=`<span class="tag">${label} · ${formatTime(e.ts)}</span><b>${safe(e.user)}${e.amount?' · '+safe(e.amount):''}</b><span>${safe(e.text)}</span>`;card.onclick=()=>featureEvent(e);recent.appendChild(card)})}
async function updateUI(){try{const r=await fetch('/api/state',{cache:'no-store'});state=await r.json();const f=state.active_flight;document.getElementById('aircraftCount').textContent=state.queue.length+' targets';const list=document.getElementById('flightList');list.innerHTML='';state.queue.forEach(item=>{const b=document.createElement('button');b.className='flight'+(f.flight===item.flight?' active':'');b.innerHTML=`<strong>${safe(item.flight)}</strong><span class="dist">${item.dist} NM</span><span class="meta">${safe(item.desc)} · ${safe(item.type)}</span><span class="meta" style="text-align:right">${safe(item.status)}</span><span class="route">${safe(item.route)} · ${item.alt_baro.toLocaleString()} ft · ${item.gs} kt</span>`;b.onclick=()=>selectFlight(item);list.appendChild(b)});document.getElementById('hudFlight').textContent=f.flight;document.getElementById('hudMeta').textContent=`${f.desc} · ${f.type} · ${f.route}`;document.getElementById('hudAlt').textContent=Number(f.alt_baro).toLocaleString()+' ft';document.getElementById('hudSpeed').textContent=f.gs+' kt';document.getElementById('hudVerticalSpeed').textContent=(Number(f.vertical_speed)>0?'+':'')+Number(f.vertical_speed).toLocaleString()+' fpm';document.getElementById('hudFlightStatus').textContent=f.status;const ar=state.ar_visible,anyHud=state.hud_logo_visible||state.hud_center_visible||state.hud_time_visible;document.getElementById('lowerThird').classList.toggle('off',!anyHud);[['logo','hud_logo_visible','previewLogo'],['center','hud_center_visible','previewCenter'],['time','hud_time_visible','previewTime']].forEach(([key,field,id])=>{const visible=state[field];document.getElementById('el'+key[0].toUpperCase()+key.slice(1)).classList.toggle('on',visible);document.getElementById('preview'+key[0].toUpperCase()+key.slice(1)).style.visibility=visible?'visible':'hidden'});document.getElementById('hudStatus').textContent=anyHud?'ON AIR':'HUD HIDDEN';document.getElementById('elTag').classList.toggle('on',ar);renderEvents(state.events||[]);animateDemoClick(state.demo_click);document.getElementById('programTime').textContent=state.program_time||'01:34:23'}catch(e){document.getElementById('hudStatus').textContent='RECONNECTING'}}
setInterval(updateUI,700);setInterval(clock,1000);setInterval(heartbeat,2000);heartbeat();updateUI();clock();
</script></body></html>"""

# --- 2. FAKE OBS STUDIO (Route: /obs ) ---
HTML_OBS_SIMULATOR = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OBS Studio Simulator · Program</title><style>
*{box-sizing:border-box}body{margin:0;background:#0b0d10;color:#d9e0e6;font:12px -apple-system,BlinkMacSystemFont,sans-serif;height:100vh;display:flex;align-items:center;justify-content:center;overflow:hidden}.obs{width:min(480px,calc((100vh - 102px)*1.77778));background:#1a1d22;border:1px solid #30343b;border-radius:10px;overflow:hidden;box-shadow:0 28px 90px #000b}.title{height:42px;background:#202329;border-bottom:1px solid #090a0c;display:flex;align-items:center;gap:9px;padding:0 15px;color:#d6dce4}.dot{width:9px;height:9px;background:#ed5965;border-radius:50%;box-shadow:14px 0 #e5b34c,28px 0 #55c273;margin-right:24px}.badge{margin-left:auto;color:#fd727e;font-size:10px;font-weight:700;letter-spacing:.14em}.canvas{position:relative;width:100%;aspect-ratio:16/9;flex:none;background:#101925;overflow:hidden}.scene{position:absolute;inset:0;transition:opacity .65s,filter .65s;overflow:hidden;background:linear-gradient(180deg,#172c42 0%,#5c8090 47%,#c3b496 48%,#56685e 65%,#263a3c 100%)}.scene:before{content:'';position:absolute;left:-10%;right:-10%;height:36%;bottom:0;background:repeating-linear-gradient(90deg,#18282b 0 5%,transparent 5% 9%),linear-gradient(0deg,#182327,#4d5d55);clip-path:polygon(0 32%,8% 28%,12% 53%,18% 48%,24% 12%,31% 15%,38% 46%,48% 44%,55% 20%,61% 29%,69% 10%,75% 12%,81% 40%,89% 33%,100% 47%,100% 100%,0 100%)}.scene:after{content:'';position:absolute;width:82%;height:45%;left:9%;bottom:-5%;background:repeating-linear-gradient(90deg,transparent 0 9%,#f1e4c4 9% 9.4%,transparent 9.4% 18%),linear-gradient(0deg,#242a28,#67736c);clip-path:polygon(44% 0,56% 0,100% 100%,0 100%);opacity:.65}.scene.video2{background:linear-gradient(180deg,#101f36 0%,#496a81 42%,#d89e65 43%,#59604f 65%,#202c31 100%)}.scene.video2:before{height:42%;background:repeating-linear-gradient(90deg,#1b292e 0 4%,transparent 4% 7%),linear-gradient(0deg,#1b272c,#70786c)}.scene.fade{opacity:.4;filter:blur(5px)}.video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .7s}.video.ready{opacity:1}.scene-label{position:absolute;left:22px;top:18px;font:600 clamp(12px,1.4vw,18px) -apple-system,sans-serif;letter-spacing:.15em;color:#fff;text-shadow:0 2px 9px #000}.source-chip{position:absolute;right:22px;top:18px;background:#101921bb;border:1px solid #ffffff42;padding:7px 11px;border-radius:20px;font-size:10px;letter-spacing:.1em}.obs-footer{height:36px;background:#202329;display:flex;align-items:center;padding:0 14px;color:#9ba5b0;gap:20px}.onair{color:#ff707d}.obs-iframe{position:absolute;left:0;top:0;width:1920px;height:1080px;transform-origin:top left;border:0;pointer-events:none}
</style></head><body><div class="obs"><div class="title"><span class="dot"></span>OBS Studio · TerminalVector Broadcast Program <span class="badge">● LIVE PROGRAM</span></div><div class="canvas"><div class="scene" id="scene"><div class="scene-label" id="sceneLabel">LOS ANGELES · LIVE CAMERA 01</div></div><video id="bgVideo" class="video" autoplay muted playsinline></video><div class="source-chip" id="sourceChip">SOURCE 01 · ACA7246</div><iframe class="obs-iframe" src="/overlay" title="TerminalVector broadcast graphics"></iframe></div><div class="obs-footer"><span class="onair">PROGRAM</span><span>1920 × 1080</span><span>30 FPS</span><span id="footerSource">ACA7246 · AIR CANADA</span><span style="margin-left:auto">TERMINALVECTOR OUTPUT</span></div></div>
<script>
let currentKey='',clipStartedKey='',videoEl=document.getElementById('bgVideo'),scene=document.getElementById('scene'),fallbackTimer=null,advancedKey='';function scaleOverlay(){const canvas=document.querySelector('.canvas');document.querySelector('.obs-iframe').style.transform=`scale(${canvas.clientWidth/1920})`}window.addEventListener('resize',scaleOverlay);scaleOverlay();async function nextClip(key){if(advancedKey===key)return;try{const state=await fetch('/api/state',{cache:'no-store'}).then(r=>r.json());if(state.automation_override_until>Date.now()/1000){setTimeout(()=>nextClip(key),1000);return}const response=await fetch('/api/next',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(response.status===409){setTimeout(()=>nextClip(key),1000);return}advancedKey=key}catch(e){setTimeout(()=>nextClip(key),1500)}}function transition(state){const f=state.active_flight,key=f.flight+':'+(state.source_version||'')+':'+(f.video||'');if(key===currentKey)return;currentKey=key;advancedKey='';clearTimeout(fallbackTimer);scene.classList.add('fade');setTimeout(()=>{scene.className='scene';const sceneClass=f.flight==='DLH456'?'video2':'';if(sceneClass)scene.classList.add(sceneClass);document.getElementById('sceneLabel').textContent=f.flight==='DLH456'?'LAX · FINAL APPROACH · CAMERA 02':'LOS ANGELES · DEPARTURE · CAMERA 01';const n=String(flightIndex(state.queue,f.flight)).padStart(2,'0');document.getElementById('sourceChip').textContent=`SOURCE ${n} · ${f.flight}`;document.getElementById('footerSource').textContent=`${f.flight} · ${f.desc.toUpperCase()}`;videoEl.classList.remove('ready');videoEl.onended=()=>nextClip(key);videoEl.onplaying=()=>{if(clipStartedKey!==key){clipStartedKey=key;fetch('/api/clip/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({flight:f.flight})})}};videoEl.onerror=()=>{videoEl.classList.remove('ready');fallbackTimer=setTimeout(()=>nextClip(key),8000)};videoEl.oncanplay=()=>{clearTimeout(fallbackTimer);videoEl.classList.add('ready');videoEl.play().catch(()=>{})};if(f.video){videoEl.src=f.video;videoEl.load();videoEl.play().catch(()=>{});fallbackTimer=setTimeout(()=>{if(videoEl.readyState<2)nextClip(key)},9000)}else{videoEl.removeAttribute('src');videoEl.load();fallbackTimer=setTimeout(()=>nextClip(key),14000)}},300)}function flightIndex(q,id){return Math.max(1,(q||[]).findIndex(x=>x.flight===id)+1)}async function heartbeat(){try{await fetch('/api/heartbeat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({client:'obs'})})}catch(e){}}document.addEventListener('pointerdown',()=>fetch('/api/override',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}));async function poll(){try{const r=await fetch('/api/state',{cache:'no-store'});transition(await r.json())}catch(e){}}setInterval(poll,300);setInterval(heartbeat,2000);heartbeat();poll();
</script></body></html>"""

# --- 3. TRANSPARENT OVERLAY (Route: /overlay ) ---
HTML_OVERLAY = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><title>TerminalVector Transparent HUD</title>
<link href="https://fonts.googleapis.com/css2?family=Onest:wght@400;600;800;900&display=swap" rel="stylesheet">
<style>
  :root { --laf-navy-dark: #0B1121; --laf-navy: #152033; --laf-gold: #F5A623; }
  body { margin: 0; background: transparent; overflow: hidden; width: 1920px; height: 1080px; font-family: 'Onest', sans-serif; color: #fff; }

  .overlay-box { position: absolute; bottom: 60px; left: 60px; width: 1800px; display: flex; height: 110px; box-shadow: 0 20px 40px rgba(0,0,0,0.8); transition: opacity 0.4s ease, transform 0.4s ease; }
  .overlay-box.center-hidden { box-shadow: none; }
  .overlay-box.hidden { opacity: 0; transform: translateY(30px); }
  .box-logo { background: var(--laf-navy-dark); padding: 0 30px; display: flex; flex-direction: column; justify-content: center; border-left: 8px solid var(--laf-gold); }
  .box-logo .la { font-size: 38px; font-weight: 900; line-height: 1; letter-spacing: -1px; }
  .box-logo .flights { font-size: 20px; font-weight: 800; color: var(--laf-gold); text-transform: uppercase; letter-spacing: 1px; }
  .box-main { background: linear-gradient(90deg, var(--laf-navy) 0%, #1c2a42 100%); flex: 1; display: flex; align-items: center; justify-content: space-between; padding: 0 40px; }

  @keyframes dataFlash { 0% { background: #ffffff; color: #000; } 100% { background: linear-gradient(90deg, var(--laf-navy) 0%, #1c2a42 100%); color: #fff; } }
  .flash-update { animation: dataFlash 0.5s ease-out; }

  .flight-callsign { font-size: 52px; font-weight: 900; letter-spacing: 1px; }
  .flight-type { font-size: 22px; font-weight: 600; color: #a1b0cb; margin-left: 15px; }
  .telemetry-grid { display: flex; gap: 40px; }
  .tel-item { display: flex; flex-direction: column; align-items: flex-start; }
  .tel-label { font-size: 14px; font-weight: 800; color: #6e84ab; text-transform: uppercase; letter-spacing: 1px; }
  .tel-val { font-size: 28px; font-weight: 800; }
  .box-time { background: linear-gradient(135deg, var(--laf-gold) 0%, #D88910 100%); padding: 0 40px; display: flex; align-items: center; justify-content: center; font-size: 36px; font-weight: 900; text-shadow: 0 2px 4px rgba(0,0,0,0.3); }

  .ar-tag { position: absolute; top: 35%; left: 65%; display: flex; align-items: center; gap: 15px; transition: top 0.2s linear, left 0.2s linear, opacity 0.3s ease; }
  .ar-tag.hidden { opacity: 0; }
  .ar-line { width: 100px; height: 3px; background: var(--laf-gold); box-shadow: 0 2px 5px rgba(0,0,0,0.5); }
  .ar-data { background: rgba(11, 17, 33, 0.90); backdrop-filter: blur(8px); padding: 12px 20px; border-left: 4px solid var(--laf-gold); border-radius: 4px; box-shadow: 0 10px 20px rgba(0,0,0,0.6); }
  .ar-data .id { font-size: 26px; font-weight: 800; }
  .ar-data .dist { font-size: 16px; font-weight: 600; color: #9ca3af; text-transform: uppercase; }

  .chat-popup { position: absolute; bottom: 200px; left: 60px; background: rgba(11, 17, 33, 0.92); backdrop-filter: blur(12px); border-left: 6px solid #3b82f6; padding: 24px 30px; width: 600px; border-radius: 0 8px 8px 0; box-shadow: 0 20px 40px rgba(0,0,0,0.8); transition: opacity 0.4s ease, transform 0.4s ease; }
  .chat-popup.superchat { border-left-color: var(--laf-gold); background: rgba(30, 20, 0, 0.95); }
  .chat-popup.donation { border-left-color: #4ce0b3; background: rgba(5, 34, 29, 0.95); }
  .chat-popup.subscription { border-left-color: #c39aff; background: rgba(31, 20, 47, 0.95); }
  .chat-popup.hidden { opacity: 0; transform: translateX(-40px); }
  .chat-header { display: flex; justify-content: space-between; font-size: 20px; margin-bottom: 12px; color: #a1b0cb; font-weight: 700; }
  .chat-popup.superchat .chat-header { color: var(--laf-gold); }
  .chat-amt { font-weight: 900; color: #fff; }
  .chat-msg { font-size: 26px; line-height: 1.4; color: #fff; font-weight: 600; }
</style>
</head>
<body>
  <div class="ar-tag" id="arTag">
    <div class="ar-line"></div>
    <div class="ar-data"><div class="id" id="dispArId">---</div><div class="dist" id="dispArStatus">---</div></div>
  </div>

  <div id="chatBox" class="chat-popup hidden">
    <div class="chat-header"><span id="chatUser">---</span><span id="chatAmt" class="chat-amt"></span></div>
    <div id="chatMsg" class="chat-msg">---</div>
  </div>

  <div id="hudBox" class="overlay-box">
    <div class="box-logo" id="boxLogo"><div class="la">LA</div><div class="flights">Flights</div></div>
    <div id="dataPanel" class="box-main">
      <div><span id="dispFlight" class="flight-callsign">---</span><span id="dispType" class="flight-type">---</span></div>
      <div class="telemetry-grid">
        <div class="tel-item"><span class="tel-label">Altitude</span><span class="tel-val"><span id="dispAlt">---</span> FT</span></div>
        <div class="tel-item"><span class="tel-label">Ground Speed</span><span class="tel-val"><span id="dispSpd">---</span> KTS</span></div>
        <div class="tel-item"><span class="tel-label">Vertical Speed</span><span class="tel-val"><span id="dispVSpeed">---</span> FPM</span></div>
        <div class="tel-item"><span class="tel-label">Status</span><span class="tel-val" id="dispStatus">FINAL</span></div>
      </div>
    </div>
    <div class="box-time" id="boxTime"><span id="live-time">10:00 AM</span></div>
  </div>

<script>
let currentFlightId = "";
function triggerAnimation() {
    const panel = document.getElementById('dataPanel');
    panel.classList.remove('flash-update'); void panel.offsetWidth; panel.classList.add('flash-update');
}

async function pollOverlay() {
  try {
    const res = await fetch('/api/state');
    const state = await res.json();

    // Time Logic (Mocked to sync with video scenarios or real time)
    const d = new Date();
    document.getElementById('live-time').innerText = d.toLocaleTimeString('en-US', {hour: '2-digit', minute:'2-digit'});

    // Visibility
    const box = document.getElementById('hudBox');
    const ar = document.getElementById('arTag');
    box.classList.toggle('center-hidden', !state.hud_center_visible);
    document.getElementById('boxLogo').style.display = state.hud_logo_visible ? 'flex' : 'none';
    document.getElementById('dataPanel').style.display = state.hud_center_visible ? 'flex' : 'none';
    document.getElementById('boxTime').style.display = state.hud_time_visible ? 'flex' : 'none';
    const anyHud = state.hud_logo_visible || state.hud_center_visible || state.hud_time_visible;
    if (state.overlay_visible && anyHud) box.classList.remove('hidden'); else box.classList.add('hidden');

    if (state.ar_visible && state.overlay_visible) {
        ar.classList.remove('hidden');
        ar.style.left = state.ar_x + '%';
        ar.style.top = state.ar_y + '%';
    } else {
        ar.classList.add('hidden');
    }

    // Chat
    const chatBox = document.getElementById('chatBox');
    if (state.chat_visible) {
      chatBox.classList.remove('hidden');
      document.getElementById('chatUser').innerText = state.chat_data.user;
      document.getElementById('chatMsg').innerText = state.chat_data.message;
      document.getElementById('chatAmt').innerText = state.chat_data.amount;
      chatBox.classList.remove('superchat', 'donation', 'subscription');
      if (state.chat_data.is_superchat) chatBox.classList.add('superchat');
      else if (state.chat_data.kind === 'donation' || state.chat_data.kind === 'subscription') chatBox.classList.add(state.chat_data.kind);
    } else chatBox.classList.add('hidden');

    // Telemetry
    const f = state.active_flight;
    if (f.flight !== currentFlightId) { currentFlightId = f.flight; triggerAnimation(); }
    document.getElementById('dispFlight').innerText = f.flight;
    document.getElementById('dispArId').innerText = f.flight;
    document.getElementById('dispArStatus').innerText = f.status;
    document.getElementById('dispType').innerText = f.desc ? f.desc + " " + f.type : f.type;
    document.getElementById('dispAlt').innerText = Number(f.alt_baro).toLocaleString();
    document.getElementById('dispSpd').innerText = f.gs;
    document.getElementById('dispVSpeed').innerText = (Number(f.vertical_speed) > 0 ? '+' : '') + Number(f.vertical_speed).toLocaleString();
    document.getElementById('dispStatus').innerText = f.status;
  } catch(e) {}
}
setInterval(pollOverlay, 200); // Fast 200ms poll for smooth slider tracking
</script>
</body></html>
"""

STATE_LOCK = threading.RLock()

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class RequestHandler(http.server.BaseHTTPRequestHandler):
    def _send(self, status, body, content_type):
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _snapshot(self):
        with STATE_LOCK:
            now = time.time()
            cutoff = now - 300
            ACTIVE_TELEMETRY["events"] = [event for event in ACTIVE_TELEMETRY["events"] if event["ts"] >= cutoff]
            if ACTIVE_TELEMETRY["alert_until"] and ACTIVE_TELEMETRY["alert_until"] < now:
                ACTIVE_TELEMETRY["chat_visible"] = False
            if ACTIVE_TELEMETRY["ar_manual_override_until"] <= now:
                flight_id = ACTIVE_TELEMETRY["active_flight"]["flight"]
                position = tracked_position(flight_id, max(0.0, now - ACTIVE_TELEMETRY["clip_started_at"]))
                if position:
                    x, y = position
                    ACTIVE_TELEMETRY["ar_x"] = round(x / TRACK_CANVAS_WIDTH * 100, 4)
                    ACTIVE_TELEMETRY["ar_y"] = round(y / TRACK_CANVAS_HEIGHT * 100, 4)
            snapshot = json.loads(json.dumps(ACTIVE_TELEMETRY))
            elapsed = max(0.0, now - ACTIVE_TELEMETRY["clip_started_at"])
            program_seconds = ACTIVE_TELEMETRY["program_time_base"] + int(elapsed)
            snapshot["program_time"] = f"{program_seconds // 3600:02d}:{(program_seconds // 60) % 60:02d}:{program_seconds % 60:02d}"
            snapshot["active_flight"] = telemetry_at(ACTIVE_TELEMETRY["active_flight"], elapsed)
            snapshot["queue"] = [
                telemetry_at(flight, elapsed if flight["flight"] == snapshot["active_flight"]["flight"] else 0.0)
                for flight in ACTIVE_TELEMETRY["queue"]
            ]
            for event in snapshot["events"]:
                event["highlighted"] = event["id"] == snapshot["featured_event_id"]
            return snapshot

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        pages = {"/": HTML_CONTROLLER, "/obs": HTML_OBS_SIMULATOR, "/overlay": HTML_OVERLAY}
        if path in pages:
            return self._send(200, pages[path], "text/html; charset=utf-8")
        if path in ("/api/state", "/health"):
            payload = self._snapshot() if path == "/api/state" else {"status": "ok", "service": "terminalvector"}
            return self._send(200, json.dumps(payload), "application/json; charset=utf-8")
        return self._send(404, json.dumps({"error": "not found"}), "application/json; charset=utf-8")

    def do_POST(self):
        global ACTIVE_TELEMETRY
        path = self.path.split("?", 1)[0]
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 65536:
                return self._send(413, json.dumps({"error": "request too large"}), "application/json; charset=utf-8")
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object")
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return self._send(400, json.dumps({"error": str(exc)}), "application/json; charset=utf-8")

        if path == "/api/clip/start":
            with STATE_LOCK:
                flight_id = str(data.get("flight", ""))
                if flight_id != ACTIVE_TELEMETRY["active_flight"]["flight"]:
                    return self._send(409, json.dumps({"error": "clip is no longer active"}), "application/json; charset=utf-8")
                ACTIVE_TELEMETRY["clip_started_at"] = time.time()
                ACTIVE_TELEMETRY["ar_manual_override_until"] = 0
            return self._send(200, json.dumps({"status": "ok"}), "application/json; charset=utf-8")
        if path == "/api/heartbeat":
            client = data.get("client")
            if client not in {"controller", "obs"}:
                return self._send(400, json.dumps({"error": "unknown client"}), "application/json; charset=utf-8")
            with STATE_LOCK:
                ACTIVE_TELEMETRY["clients"][client] = time.time()
            return self._send(200, json.dumps({"status": "ok"}), "application/json; charset=utf-8")
        if path == "/api/override":
            with STATE_LOCK:
                ACTIVE_TELEMETRY["automation_override_until"] = time.time() + 10
            return self._send(200, json.dumps({"status": "ok", "seconds": 10}), "application/json; charset=utf-8")

        if path not in {"/api/next", "/api/demo/action", "/api/clip/start"}:
            with STATE_LOCK:
                ACTIVE_TELEMETRY["automation_override_until"] = time.time() + 10

        with STATE_LOCK:
            if path == "/api/demo/action":
                action = data.get("action")
                click_id = str(time.time_ns())
                targets = {"toggle_logo": "elLogo", "toggle_center": "elCenter", "toggle_time": "elTime", "toggle_tag": "elTag"}
                if action not in targets and action not in {"chat", "superchat", "subscription", "donation"}:
                    return self._send(400, json.dumps({"error": "unknown demo action"}), "application/json; charset=utf-8")
                target = targets[action] if action in targets else ("chat-" if action == "chat" else "alert-") + click_id
                ACTIVE_TELEMETRY["demo_click"] = {"id": click_id, "target": target}
                ACTIVE_TELEMETRY["demo_action"] = action + "-" + click_id
                if action in {"toggle_logo", "toggle_center", "toggle_time"}:
                    element = {"toggle_logo": "logo", "toggle_center": "center", "toggle_time": "time"}[action]
                    field = "hud_" + element + "_visible"
                    ACTIVE_TELEMETRY[field] = bool(data["visible"]) if "visible" in data else not ACTIVE_TELEMETRY[field]
                elif action == "toggle_tag":
                    ACTIVE_TELEMETRY["ar_visible"] = bool(data["visible"]) if "visible" in data else not ACTIVE_TELEMETRY["ar_visible"]
                else:
                    kind = "chat" if action == "chat" else action
                    event = {"id": click_id, "ts": time.time(), "kind": kind, "user": str(data.get("user", "Viewer"))[:80], "text": str(data.get("text", ""))[:500], "amount": str(data.get("amount", ""))[:40]}
                    ACTIVE_TELEMETRY["events"].append(event)
                    ACTIVE_TELEMETRY["chat_visible"] = True
                    ACTIVE_TELEMETRY["chat_data"] = {"user": event["user"], "message": event["text"], "amount": event["amount"], "is_superchat": kind == "superchat", "kind": kind}
                    ACTIVE_TELEMETRY["alert_until"] = time.time() + 7
                return self._send(200, json.dumps({"status": "ok", "state": self._snapshot()}), "application/json; charset=utf-8")
            elif path == "/api/next":
                if ACTIVE_TELEMETRY["automation_override_until"] > time.time():
                    return self._send(409, json.dumps({"error": "manual override active"}), "application/json; charset=utf-8")
                current = ACTIVE_TELEMETRY["active_flight"]["flight"]
                clips = FALLBACK_MOCK_PLANES[:2]
                index = next((i for i, flight in enumerate(clips) if flight["flight"] == current), -1)
                selected = clips[(index + 1) % len(clips)]
                ACTIVE_TELEMETRY["active_flight"] = selected
                ACTIVE_TELEMETRY["clip_started_at"] = time.time()
                ACTIVE_TELEMETRY["program_time_base"] = PROGRAM_START_TIMES.get(selected["flight"], PROGRAM_START_TIMES["ACA7246"])
                ACTIVE_TELEMETRY["ar_manual_override_until"] = 0
                ACTIVE_TELEMETRY["source_version"] += 1
                ACTIVE_TELEMETRY["demo_action"] = "next-" + str(time.time_ns())
                return self._send(200, json.dumps({"status": "ok", "flight": selected["flight"]}), "application/json; charset=utf-8")
            elif path == "/api/toggle":
                ACTIVE_TELEMETRY["overlay_visible"] = not ACTIVE_TELEMETRY["overlay_visible"]
                ACTIVE_TELEMETRY["demo_action"] = "lower-third-" + str(time.time_ns())
            elif path == "/api/toggle_ar":
                ACTIVE_TELEMETRY["ar_visible"] = not ACTIVE_TELEMETRY["ar_visible"]
                ACTIVE_TELEMETRY["demo_action"] = "aircraft-tag-" + str(time.time_ns())
            elif path == "/api/hud/element":
                fields = {"logo": "hud_logo_visible", "center": "hud_center_visible", "time": "hud_time_visible"}
                element = data.get("element")
                if element not in fields:
                    return self._send(400, json.dumps({"error": "unknown HUD element"}), "application/json; charset=utf-8")
                ACTIVE_TELEMETRY[fields[element]] = not ACTIVE_TELEMETRY[fields[element]]
                ACTIVE_TELEMETRY["demo_action"] = "hud-" + element + "-" + str(time.time_ns())
            elif path == "/api/tracker":
                try:
                    ACTIVE_TELEMETRY["ar_x"] = max(0, min(100, float(data.get("x", 65))))
                    ACTIVE_TELEMETRY["ar_y"] = max(0, min(100, float(data.get("y", 35))))
                    ACTIVE_TELEMETRY["ar_manual_override_until"] = time.time() + 10
                except (TypeError, ValueError):
                    return self._send(400, json.dumps({"error": "x and y must be integers"}), "application/json; charset=utf-8")
            elif path == "/api/chat":
                visible = bool(data.get("visible", False))
                ACTIVE_TELEMETRY["chat_visible"] = visible
                if visible:
                    ACTIVE_TELEMETRY["chat_data"] = {
                        "user": str(data.get("user", ""))[:80],
                        "message": str(data.get("msg", ""))[:500],
                        "amount": str(data.get("amt", ""))[:40],
                        "is_superchat": bool(data.get("superchat", False)),
                    }
            elif path == "/api/select":
                flight_id = data.get("flight")
                selected = next((flight for flight in FALLBACK_MOCK_PLANES if flight["flight"] == flight_id), None)
                if selected is None:
                    return self._send(400, json.dumps({"error": "unknown flight"}), "application/json; charset=utf-8")
                if ACTIVE_TELEMETRY["active_flight"]["flight"] != flight_id:
                    ACTIVE_TELEMETRY["source_version"] += 1
                ACTIVE_TELEMETRY["active_flight"] = selected
                ACTIVE_TELEMETRY["clip_started_at"] = time.time()
                ACTIVE_TELEMETRY["program_time_base"] = PROGRAM_START_TIMES.get(selected["flight"], PROGRAM_START_TIMES["ACA7246"])
                ACTIVE_TELEMETRY["ar_manual_override_until"] = 0
                ACTIVE_TELEMETRY["overlay_visible"] = True
                ACTIVE_TELEMETRY["demo_action"] = "flight-" + flight_id
            elif path == "/api/event":
                kind = str(data.get("kind", "chat"))
                if kind not in {"chat", "superchat", "donation", "subscription"}:
                    return self._send(400, json.dumps({"error": "invalid event kind"}), "application/json; charset=utf-8")
                event = {
                    "id": str(data.get("id") or str(time.time_ns())),
                    "ts": time.time(), "kind": kind,
                    "user": str(data.get("user", "Viewer"))[:80],
                    "text": str(data.get("text", ""))[:500],
                    "amount": str(data.get("amount", ""))[:40],
                }
                ACTIVE_TELEMETRY["events"].append(event)
                ACTIVE_TELEMETRY["demo_action"] = "event-" + event["id"]
                if kind != "chat":
                    ACTIVE_TELEMETRY["chat_visible"] = True
                    ACTIVE_TELEMETRY["chat_data"] = {
                        "user": event["user"], "message": event["text"],
                        "amount": event["amount"], "is_superchat": kind == "superchat",
                        "kind": kind,
                    }
                    ACTIVE_TELEMETRY["alert_until"] = time.time() + 7
            elif path == "/api/feature":
                event_id = str(data.get("id", ""))
                match = next((event for event in ACTIVE_TELEMETRY["events"] if event["id"] == event_id), None)
                if match is None:
                    return self._send(404, json.dumps({"error": "event not found"}), "application/json; charset=utf-8")
                ACTIVE_TELEMETRY["featured_event_id"] = event_id
                ACTIVE_TELEMETRY["chat_visible"] = True
                ACTIVE_TELEMETRY["chat_data"] = {
                    "user": match["user"], "message": match["text"],
                    "amount": match["amount"], "is_superchat": match["kind"] == "superchat",
                    "kind": match["kind"],
                }
                ACTIVE_TELEMETRY["alert_until"] = time.time() + 8
                ACTIVE_TELEMETRY["demo_action"] = "feature-" + event_id
            else:
                return self._send(404, json.dumps({"error": "not found"}), "application/json; charset=utf-8")

        return self._send(200, json.dumps({"status": "ok", "state": self._snapshot()}), "application/json; charset=utf-8")

    def log_message(self, format, *args):
        pass

def run_server():
    with ThreadingHTTPServer(("0.0.0.0", PORT), RequestHandler) as httpd:
        print(f"TerminalVector listening on 0.0.0.0:{PORT}", flush=True)
        httpd.serve_forever()

if __name__ == "__main__":
    run_server()
