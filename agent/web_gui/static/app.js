/* ══════════════════════════════════════════════════
   ClaudeZ Web v2 — Claude Code-style UI
   ══════════════════════════════════════════════════
   - Particle canvas background
   - SSE streaming text accumulation
   - Tool calls with paths, timing, diffs
   - Side panels: tools, events, config
   ══════════════════════════════════════════════════ */
(function(){'use strict';

// ─── STATE ───
var S={
  busy:0, last:'', ab:1, sse:null,
  toolCount:0, events:[], evFilter:'all',
};

function ts(){return new Date().toLocaleTimeString()}
function div(c){var d=document.createElement('div');d.className=c;return d}
function $(id){return document.getElementById(id)}
function esc(s){var d=document.createElement('div');d.textContent=s;return d.innerHTML}
function scrollB(){msgs.scrollTop=msgs.scrollHeight}

// ─── DOM ───
var msgs=$('msgs'), ib=$('inp'), sb=$('send-btn'), st=$('st-t'), hds=$('hd-s');
var toasts=$('toasts'), scrollH=$('scroll-hint');

// ══════════════════════════════════════════════════
// PARTICLE BACKGROUND
// ══════════════════════════════════════════════════
(function(){
  var cv=$('bg-canvas'), ctx=cv.getContext('2d'), W,H, parts=[], mx=0,my=0, ma=0;
  var COLORS=['0,212,255','124,58,237','244,114,182','52,211,153'];
  function resize(){W=cv.width=window.innerWidth;H=cv.height=window.innerHeight}
  resize(); window.addEventListener('resize',resize);
  for(var i=0;i<120;i++){
    parts.push({
      x:Math.random()*W,y:Math.random()*H,
      vx:(Math.random()-0.5)*0.5,vy:(Math.random()-0.5)*0.5,
      r:Math.random()*2+0.5,o:Math.random()*0.4+0.1,
      c:COLORS[Math.floor(Math.random()*4)],
      ps:Math.random()*0.02+0.005,po:Math.random()*Math.PI*2,
    });
  }
  document.addEventListener('mousemove',function(e){mx=e.clientX;my=e.clientY;ma=1});
  document.addEventListener('mouseleave',function(){ma=0});
  function anim(t){
    ctx.clearRect(0,0,W,H);
    for(var i=0;i<parts.length;i++){
      var p=parts[i];p.x+=p.vx;p.y+=p.vy;
      if(p.x<0||p.x>W)p.vx*=-1;if(p.y<0||p.y>H)p.vy*=-1;
      var d=ma?Math.hypot(p.x-mx,p.y-my):999;
      var sc=d<150?1+(1-d/150)*1.5:1;
      var ro=p.o*(0.7+0.3*Math.sin(t*p.ps+p.po));
      if(d<80)ro=Math.min(1,ro+0.4);
      ctx.beginPath();ctx.arc(p.x,p.y,p.r*sc,0,Math.PI*2);
      ctx.fillStyle='rgba('+p.c+','+ro+')';ctx.fill();
    }
    for(var i=0;i<parts.length;i++){
      for(var j=i+1;j<parts.length;j++){
        var dx=parts[i].x-parts[j].x,dy=parts[i].y-parts[j].y,dist=Math.hypot(dx,dy);
        if(dist<120){
          ctx.beginPath();ctx.moveTo(parts[i].x,parts[i].y);ctx.lineTo(parts[j].x,parts[j].y);
          ctx.strokeStyle='rgba(124,58,227,'+(1-dist/120)*0.12+')';ctx.lineWidth=0.5;ctx.stroke();
        }
      }
    }
    if(ma){
      for(var i=0;i<parts.length;i++){
        var dx=parts[i].x-mx,dy=parts[i].y-my,dist=Math.hypot(dx,dy);
        if(dist<180){
          ctx.beginPath();ctx.moveTo(parts[i].x,parts[i].y);ctx.lineTo(mx,my);
          ctx.strokeStyle='rgba(0,212,255,'+(1-dist/180)*0.2+')';ctx.lineWidth=0.6;ctx.stroke();
        }
      }
    }
    requestAnimationFrame(anim);
  }
  anim(0);
})();

// ══════════════════════════════════════════════════
// MARKDOWN RENDER
// ══════════════════════════════════════════════════
function md(text){
  if(!text) return '';
  var h = text, cbs = [], ics = [];

  h = h.replace(/```(\w*)\n?([\s\S]*?)```/g, function(m, l, c) {
    var i = cbs.length;
    cbs.push('<pre><code>' + esc(c) + '</code></pre>');
    return '%%CB' + i + '%%';
  });
  h = h.replace(/`([^`]+)`/g, function(m, c) {
    var i = ics.length;
    ics.push('<code>' + esc(c) + '</code>');
    return '%%IC' + i + '%%';
  });
  h = h.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  h = h.replace(/^# (.+)$/gm, '<b style="font-size:16px;color:var(--accent)">$1</b>');
  h = h.replace(/^## (.+)$/gm, '<b style="font-size:14px">$1</b>');
  h = h.replace(/%%CB(\d+)%%/g, function(m, i) { return cbs[parseInt(i)] || ''; });
  h = h.replace(/%%IC(\d+)%%/g, function(m, i) { return ics[parseInt(i)] || ''; });
  h = h.replace(/\n/g, '<br>');
  return h;
}

// ══════════════════════════════════════════════════
// TOOL ICONS
// ══════════════════════════════════════════════════
var I={
  read:'📖',write:'✏️',edit:'🔧',glob:'🔎',grep:'🔎',
  bash:'💻',web:'🌐',web_search:'🔍',
  process:'⚙️',monitor:'📊',subagent:'🧠',
  artifact:'📦',workflow:'📋',webhook:'🔌',
  plan:'📋',task:'✅',
};

// ══════════════════════════════════════════════════
// DIFF DETECTION & RENDER
// ══════════════════════════════════════════════════
function hasDiff(t){return t.indexOf('@@ -')>=0||(t.indexOf('\n+')>=0&&t.indexOf('\n-')>=0)||t.indexOf('+++')>=0}

var LM={py:'python',js:'javascript',ts:'typescript',jsx:'javascript',tsx:'typescript',
  html:'html',css:'css',json:'json',md:'markdown',yaml:'yaml',yml:'yaml',
  rs:'rust',go:'go',java:'java',cpp:'cpp',c:'c',sh:'bash',bash:'bash',
  sql:'sql',xml:'xml',php:'php',rb:'ruby',swift:'swift',kt:'kotlin'};

function hl(line,lang){
  var h=esc(line);
  var kws=['function ','def ','class ','return ','if ','else ','elif ','for ','while ','import ','from ','export ','const ','let ','var ','async ','await ','try ','catch ','throw ','new ','this ','null ','undefined ','true ','false ','None ','True ','False ','self ','public ','private ','static ','interface ','enum ','type ','package ','struct ','impl ','trait ','fn ','mut ','pub ','in ','not ','and ','or ','is ','lambda ','yield ','with ','as ','except ','finally ','raise ','pass ','break ','continue ','switch ','case ','default '];
  kws.forEach(function(kw){
    var re=new RegExp('(^|\\W)('+kw.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+')(?=\\W|$)','g');
    h=h.replace(re,'$1<span style="color:#7c3aed;font-weight:600">$2</span>');
  });
  h=h.replace(/(&lt;!--[\s\S]*?--&gt;|#.+$|\/\/.+$)/gm,'<span style="color:#555580;font-style:italic">$1</span>');
  h=h.replace(/("(?:[^"\\]|\\.)*")/g,'<span style="color:#ce9178">$1</span>');
  h=h.replace(/('(?:[^'\\]|\\.)*')/g,'<span style="color:#ce9178">$1</span>');
  return h;
}

function renderDiff(refEl, diffText, filePath){
  var lines=diffText.split('\n');
  var db=div('diff-block');
  var lang='';
  if(filePath){var ext=filePath.split('.').pop().toLowerCase();lang=LM[ext]||'';}
  var add=0,del=0;
  lines.forEach(function(l){
    if(l.startsWith('+')&&!l.startsWith('+++'))add++;
    if(l.startsWith('-')&&!l.startsWith('---'))del++;
  });
  var plusMinus=(add?'+'+add:'')+(del?'  -'+del:'');
  var hdr=div('diff-hdr');
  hdr.innerHTML='<span>📝 '+plusMinus+(lang?'  ·  '+lang:'')+'</span><span style="margin-left:auto;font-size:10px">收起</span>';
  hdr.onclick=function(){db.classList.toggle('closed');hdr.querySelector('span:first-child').textContent=db.classList.contains('closed')?'▶ '+plusMinus:'📝 '+plusMinus;};
  var body=div('diff-body');
  var lineNum=0;
  lines.forEach(function(l){
    if(l.startsWith('@@')){var h=div('diff-hunk');h.textContent=l;body.appendChild(h);var m=l.match(/@@\s+-\d+(?:,\d+)?\s+\+(\d+)/);if(m)lineNum=parseInt(m[1])-1;return;}
    if(l.startsWith('---')||l.startsWith('+++')||l.startsWith('\\ ')) return;
    var dl=div('diff-line');
    if(l.startsWith('+')){
      dl.className+=' diff-add';
      dl.innerHTML='<span class="diff-num"></span><span class="diff-sig">+</span><span class="diff-code">'+hl(l.substring(1),lang)+'</span>';
    }else if(l.startsWith('-')){
      dl.className+=' diff-del';
      dl.innerHTML='<span class="diff-num"></span><span class="diff-sig">-</span><span class="diff-code">'+hl(l.substring(1),lang)+'</span>';
    }else{
      var ctx=l.startsWith(' ')?l.substring(1):l;
      dl.className+=' diff-ctx';
      lineNum++;
      dl.innerHTML='<span class="diff-num">'+lineNum+'</span><span class="diff-sig"> </span><span class="diff-code">'+esc(ctx)+'</span>';
    }
    body.appendChild(dl);
  });
  db.appendChild(hdr);db.appendChild(body);
  refEl.parentNode.insertBefore(db,refEl.nextSibling);
  scrollB();
  var total=body.querySelectorAll('.diff-line').length;
  if(total>30){db.classList.add('closed');hdr.querySelector('span:first-child').textContent='▶ '+plusMinus;}
  if(total>50){body.style.maxHeight='300px';body.style.overflowY='auto';}
}

// ══════════════════════════════════════════════════
// CHAT MESSAGES
// ══════════════════════════════════════════════════

// Stream text accumulator
function addText(delta){
  var last=msgs.lastElementChild;
  if(last&&last.classList.contains('msg-asst')){
    last._acc=(last._acc||'')+delta;
    var mc=last.querySelector('.mc');
    if(mc) mc.innerHTML=md(last._acc);
  }else{
    var el=div('msg msg-asst');
    el.innerHTML='<div class="mc">'+md(delta)+'</div><div class="mt">'+ts()+'</div>';
    el._acc=delta;
    msgs.appendChild(el);
  }
  scrollB();
}

function addUser(text){
  var el=div('msg msg-user');
  el.innerHTML='<div class="mc">'+esc(text)+'</div><div class="mt">'+ts()+'</div>';
  msgs.appendChild(el);scrollB();
}

// Tool call
var _toolSeq=0;
function addToolCall(name, path, extra){
  var icon=I[name]||'⚡';
  var extraHtml=extra?' <span class="tl-extra">'+esc(extra)+'</span>':'';
  var pathHtml=path?'<span class="tl-target">'+esc(path)+'</span>':'';
  var seq=++_toolSeq;
  var el=div('tool-line');
  el.dataset.tseq=seq;
  el.dataset.tname=name;
  el.innerHTML='<span class="tl-icon">'+icon+'</span>'
    +'<span class="tl-name">'+name+'</span>'
    +pathHtml+extraHtml
    +'<span class="tl-status">⏳</span>';
  msgs.appendChild(el);scrollB();
  // Step separator every 3 tools
  var tl=msgs.querySelectorAll('.tool-line');
  if(tl.length>=3&&tl.length%3===0){
    var sep=div('step-sep step-done');
    sep.textContent='✔ '+(tl.length)+' 工具调用';
    msgs.appendChild(sep);scrollB();
  }
  return el;
}

function addToolResult(name, isErr, durMs, resultText, toolPath){
  var tools=msgs.querySelectorAll('.tool-line');
  var tc=null;
  for(var i=0;i<tools.length;i++){
    if(tools[i].dataset.tname===name){
      var st=tools[i].querySelector('.tl-status');
      if(st&&st.textContent==='⏳'){tc=tools[i];break;}
    }
  }
  if(!tc){
    for(var i=0;i<tools.length;i++){
      var st=tools[i].querySelector('.tl-status');
      if(st&&st.textContent==='⏳'){tc=tools[i];break;}
    }
  }
  if(!tc) return;

  var st=tc.querySelector('.tl-status');
  var durStr=durMs?' <span class="tl-time">'+(durMs/1000).toFixed(1)+'s</span>':'';
  if(isErr){st.innerHTML='❌'+durStr;st.className='tl-status tl-err';}
  else{st.innerHTML='✅'+durStr;st.className='tl-status tl-done';}

  S.toolCount++;$('st-c').textContent=S.toolCount;

  if(resultText&&hasDiff(resultText)){renderDiff(tc, resultText, toolPath||'');}
}

// Thinking
function addThink(text){
  var last=msgs.lastElementChild;
  if(last&&last.classList.contains('think-block')){
    var b=last.querySelector('.think-b');
    if(b){b.textContent+=text;scrollB();return last;}
  }
  var el=div('think-block');
  el.innerHTML='<div class="think-h">🧠 思考</div><div class="think-b">'+esc(text)+'</div>';
  msgs.appendChild(el);
  el.querySelector('.think-h').onclick=function(){el.classList.toggle('collapsed');};
  scrollB();return el;
}

function addSys(text){
  var el=div('msg msg-sys');
  el.innerHTML='<div class="mc">'+esc(text)+'</div>';
  msgs.appendChild(el);scrollB();
}

function addErr(text){
  var el=div('msg msg-err');
  el.innerHTML='<div class="mc">'+esc(text)+'</div>';
  msgs.appendChild(el);scrollB();
}

// ══════════════════════════════════════════════════
// SSE
// ══════════════════════════════════════════════════
function connectSSE(){
  if(S.sse) S.sse.close();
  S.sse=new EventSource('/api/stream');

  // 内容块增量事件（Claude Code 规范）
  S.sse.addEventListener('text_delta',function(e){
    try{var d=JSON.parse(e.data);if(d.delta)addText(d.delta);}catch(x){}
  });

  S.sse.addEventListener('thinking_delta',function(e){
    try{var d=JSON.parse(e.data);if(d.delta)addThink(d.delta);}catch(x){}
  });

  // 工具调用生命周期
  S.sse.addEventListener('tool_use_start',function(e){
    try{var d=JSON.parse(e.data);
      addToolCall(d.tool_name,d.file_path||'',d.args_preview||'');addEvent('tool','→ '+d.tool_name+(d.file_path?' '+d.file_path:''));
      setBusy(1);
    }catch(x){}
  });

  S.sse.addEventListener('tool_result',function(e){
    try{var d=JSON.parse(e.data);
      addToolResult(d.tool_name,d.status==='error',d.duration_ms||0,d.result||'',d.file_path||'');
      addEvent('tool',(d.status==='error'?'✗ ':'✔ ')+d.tool_name+(d.duration_ms?' '+(d.duration_ms/1000).toFixed(1)+'s':''));
    }catch(x){}
  });

  // 会话生命周期
  S.sse.addEventListener('session_start',function(e){
    try{setBusy(1);addEvent('session','▶ start');}catch(x){}
  });
  S.sse.addEventListener('session_end',function(e){
    try{setBusy(0);addEvent('session','■ end');if(window.C&&window.C.updateDebugSummary)window.C.updateDebugSummary();}catch(x){}
  });

  // 工具实时输出（bash stdout/stderr 逐行）
  S.sse.addEventListener('tool_output',function(e){
    try{var d=JSON.parse(e.data);
      var line=d.line||'';
      // 找最后一条匹配工具名的 tool-line，追加输出
      var tools=msgs.querySelectorAll('.tool-line');
      var el=null;
      for(var i=tools.length-1;i>=0;i--){
        if(tools[i].dataset.tname===d.tool_name){el=tools[i];break;}
      }
      if(!el){
        // 没有 tool-line → 创建一个
        addToolCall(d.tool_name,'','');
        el=msgs.lastElementChild;
      }
      // 追加输出行
      var out=el.querySelector('.tl-output');
      if(!out){
        out=document.createElement('div');
        out.className='tl-output';
        out.style.cssText='font-size:11px;color:var(--fg-3);padding:2px 0 2px 26px;font-family:var(--font-mono);white-space:pre-wrap;word-break:break-all';
        el.appendChild(out);
      }
      out.textContent+=line+'\n';
      scrollB();
    }catch(x){}
  });

  S.sse.addEventListener('error',function(e){
    try{var d=JSON.parse(e.data);if(d.message){addErr(d.message);setBusy(0);addEvent('error',d.message);}}catch(x){}
  });
}

// ══════════════════════════════════════════════════
// SEND / STOP / CLEAR
// ══════════════════════════════════════════════════
function send(){
  if(S._sending) return;
  var t=ib.value.trim();if(!t||S.busy)return;
  S.last=t;ib.value='';ib.style.height='auto';
  S._sending = true;
  setBusy(1);addUser(t);
  fetch('/api/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:t})})
    .then(function(r){return r.json()})
    .then(function(d){if(d.status!=='ok'){addErr(d.message||'发送失败');setBusy(0);} S._sending=false;})
    .catch(function(e){addErr('网络错误: '+e.message);setBusy(0); S._sending=false;});
}

function stop(){if(!S.busy)return;fetch('/api/stop',{method:'POST'}).catch(function(){});setBusy(0);addSys('⏹ 已终止');}

function clear(){
  msgs.innerHTML='';
  S.toolCount=0;S.events=[];$('st-c').textContent='0';
  $('ev-c').innerHTML='<div style="padding:20px;text-align:center;color:var(--fg-3);font-size:12px">等待事件...</div>';
  fetch('/api/clear',{method:'POST'}).catch(function(){});
  addSys('🗑 对话已清空');
  toast('对话已清空','info');
}

function setBusy(b){
  S.busy=b;sb.disabled=b;sb.textContent=b?'...':'发送';ib.disabled=b;$('btn-stop').disabled=!b;
  if(b){hds.className='hd-status busy';st.textContent='工作中';}else{hds.className='hd-status';st.textContent='就绪';}
}

// ══════════════════════════════════════════════════
// EVENT LOG
// ══════════════════════════════════════════════════
var EV_TYPES=['all','session','tool','thought','text','error'];
function renderEvFilters(){
  var c=$('ev-fil');c.innerHTML='';
  EV_TYPES.forEach(function(t){
    var b=document.createElement('button');b.className='ev-f'+(t==='all'?' act':'');b.textContent=t;
    b.onclick=function(){c.querySelectorAll('.ev-f').forEach(function(x){x.classList.remove('act')});b.classList.add('act');S.evFilter=t;renderEvLog();};
    c.appendChild(b);
  });
}

function addEvent(type,data){
  S.events.push({type:type,data:data||'',ts:Date.now()});
  if(S.events.length>500)S.events.shift();
  renderEvLog();
}

function renderEvLog(){
  var c=$('ev-c');
  var filtered=S.evFilter==='all'?S.events:S.events.filter(function(e){return e.type===S.evFilter});
  if(filtered.length===0){c.innerHTML='<div style="padding:20px;text-align:center;color:var(--fg-3);font-size:12px">'+(S.evFilter==='all'?'等待事件...':'无 '+S.evFilter+' 事件')+'</div>';return;}
  var show=filtered.slice(-80);
  var h='';
  show.forEach(function(e){
    var t=new Date(e.ts).toLocaleTimeString();
    var d=typeof e.data==='string'?e.data:JSON.stringify(e.data);
    h+='<div class="ev-item"><span class="ev-tm">'+t+'</span><span class="ev-ty '+e.type+'">'+e.type.substring(0,4)+'</span><span class="ev-da">'+esc(d.substring(0,80))+'</span></div>';
  });
  c.innerHTML=h;c.scrollTop=c.scrollHeight;
}

// ══════════════════════════════════════════════════
// TOOLS PANEL
// ══════════════════════════════════════════════════
var TCATS=[
  {n:'📁 文件',c:'#60a5fa',ts:['read','write','edit','glob','grep']},
  {n:'💻 命令',c:'#34d399',ts:['bash']},
  {n:'🌐 网络',c:'#fb923c',ts:['web','web_search']},
  {n:'🖥️ 系统',c:'#f472b6',ts:['process','monitor']},
  {n:'📦 制品',c:'#38bdf8',ts:['artifact']},
  {n:'🧠 子Agent',c:'#c084fc',ts:['subagent']},
  {n:'📋 工作流',c:'#34d399',ts:['workflow']},
  {n:'🔌 Webhook',c:'#fbbf24',ts:['webhook']},
];

window._toolStats={};
function buildTools(){
  var c=$('tools-c');c.innerHTML='';
  TCATS.forEach(function(cat){
    var hdr=div('tool-cat');hdr.style.color=cat.c;hdr.textContent=cat.n+' ('+cat.ts.length+')';c.appendChild(hdr);
    var g=div('tool-grd');
    cat.ts.forEach(function(name){
      window._toolStats[name]=0;
      var el=div('tool-item');
      el.innerHTML='<span class="td idle" id="td-'+name+'"></span><span class="ti">'+(I[name]||'⚡')+'</span><span class="tn">'+name+'</span><span class="tc" id="tcnt-'+name+'">0</span>';
      g.appendChild(el);
    });
    c.appendChild(g);
  });
}

function updateTD(name,status){
  var d=$('td-'+name);if(d){d.className='td '+status;}
  if(status==='done'||status==='error'){
    window._toolStats[name]=(window._toolStats[name]||0)+1;
    var cnt=$('tcnt-'+name);if(cnt)cnt.textContent=window._toolStats[name];
  }
}

var _origAddToolResult=addToolResult;
addToolResult=function(name,isErr,durMs,resultText,path){
  _origAddToolResult(name,isErr,durMs,resultText,path);
  updateTD(name,isErr?'error':'done');
};
var _origAddToolCall=addToolCall;
addToolCall=function(name,path,extra){
  updateTD(name,'running');
  _origAddToolCall(name,path,extra);
};

// ══════════════════════════════════════════════════
// CONFIG
// ══════════════════════════════════════════════════
function buildConfig(){
  var c=$('cfg-c');
  c.innerHTML='<div class="cfg-g"><label class="cfg-l">Model</label><input class="cfg-i" type="text" id="cfg-m" placeholder="claude-sonnet-4-20250514"></div>'
    +'<div class="cfg-g"><label class="cfg-l">Workflow Mode</label><select class="cfg-s" id="cfg-w"><option value="agent">Agent</option><option value="chat">Chat</option><option value="research">Research</option><option value="coding">Coding</option><option value="debug">Debug</option></select></div>'
    +'<button class="cfg-btn" onclick="C.saveConfig()">💾 保存配置</button>'
    +'<div id="cfg-st" style="margin-top:6px;font-size:11px;color:var(--fg-3);display:none"></div>';
  fetch('/api/config').then(function(r){return r.json()}).then(function(d){
    if(d.model)$('cfg-m').value=d.model;
    if(d.workflow_mode)$('cfg-w').value=d.workflow_mode;
    $('st-m').textContent=d.model||'—';
  }).catch(function(){});
}

// ══════════════════════════════════════════════════
// TOAST
// ══════════════════════════════════════════════════
function toast(msg,t){
  t=t||'info';
  var el=div('toast'+(t==='success'?' s':t==='error'?' e':''));
  el.innerHTML=(t==='success'?'✅':t==='error'?'❌':'ℹ️')+' '+msg;
  toasts.appendChild(el);
  setTimeout(function(){el.classList.add('out');setTimeout(function(){el.remove();},250);},3000);
}

// ══════════════════════════════════════════════════
// SCROLL
// ══════════════════════════════════════════════════
msgs.addEventListener('scroll',function(){
  var th=60;S.ab=(msgs.scrollHeight-msgs.scrollTop-msgs.clientHeight)<th;
  scrollH.classList.toggle('show',!S.ab);
});
scrollH.onclick=function(){S.ab=1;scrollB();this.classList.remove('show');};

// ══════════════════════════════════════════════════
// EXPORTS
// ══════════════════════════════════════════════════
window.C={
  send:send,stop:stop,clear:clear,
  exportDebug:function(){
    fetch('/api/debug').then(function(r){return r.text()}).then(function(t){
      if(navigator.clipboard) navigator.clipboard.writeText(t).then(function(){toast('✅ 调试日志(JSON)已复制','success')}).catch(function(){})
      else{var ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();toast('✅ 已复制','success')}
    }).catch(function(){toast('❌ 导出失败','error')});
  },
  exportDebugMD:function(){
    fetch('/api/debug/markdown').then(function(r){return r.text()}).then(function(t){
      if(navigator.clipboard) navigator.clipboard.writeText(t).then(function(){toast('✅ 调试报告(Markdown)已复制','success')}).catch(function(){})
      else{var ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();toast('✅ 已复制','success')}
    }).catch(function(){toast('❌ 导出失败','error')});
  },
  updateDebugSummary:function(){
    fetch('/api/debug/summary').then(function(r){return r.json()}).then(function(d){
      var el=$('dbg-summary');
      if(!el||!d||!d.total_tool_calls&&d.total_tool_calls!==0) return;
      el.innerHTML='<div style="display:grid;grid-template-columns:1fr 1fr;gap:4px">'
        +'<div style="padding:6px;background:rgba(255,255,255,0.03);border-radius:4px"><div style="font-size:10px;color:var(--fg-3)">工具调用</div><div style="font-size:16px;font-weight:600;color:var(--accent7)">'+d.total_tool_calls+'</div></div>'
        +'<div style="padding:6px;background:rgba(255,255,255,0.03);border-radius:4px"><div style="font-size:10px;color:var(--fg-3)">API调用</div><div style="font-size:16px;font-weight:600;color:var(--accent)">'+d.total_api_calls+'</div></div>'
        +'<div style="padding:6px;background:rgba(255,255,255,0.03);border-radius:4px"><div style="font-size:10px;color:var(--fg-3)">成功</div><div style="font-size:16px;font-weight:600;color:var(--accent4)">'+d.successful_tools+'</div></div>'
        +'<div style="padding:6px;background:rgba(255,255,255,0.03);border-radius:4px"><div style="font-size:10px;color:var(--fg-3)">失败</div><div style="font-size:16px;font-weight:600;color:var(--accent6)">'+d.failed_tools+'</div></div>'
        +'<div style="padding:6px;background:rgba(255,255,255,0.03);border-radius:4px"><div style="font-size:10px;color:var(--fg-3)">工具耗时</div><div style="font-size:14px;font-weight:600;color:var(--fg-2)">'+(d.total_tool_duration_ms/1000).toFixed(1)+'s</div></div>'
        +'<div style="padding:6px;background:rgba(255,255,255,0.03);border-radius:4px"><div style="font-size:10px;color:var(--fg-3)">API耗时</div><div style="font-size:14px;font-weight:600;color:var(--fg-2)">'+(d.total_api_duration_ms/1000).toFixed(1)+'s</div></div>'
        +'</div>';
    }).catch(function(){});
  },
  saveConfig:function(){
    var m=$('cfg-m'),w=$('cfg-w');
    var body={};
    if(m.value.trim())body.model=m.value.trim();
    if(w.value)body.workflow_mode=w.value;
    if(!body.model&&!body.workflow_mode){toast('请输入模型名称','error');return;}
    fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
      .then(function(r){return r.json()}).then(function(d){
        if(d.status==='ok'){$('st-m').textContent=m.value||$('st-m').textContent;var st=$('cfg-st');st.style.display='block';st.style.color='var(--accent4)';st.textContent='✅ 保存成功';toast('✅ 配置已保存','success');}
        else{var st=$('cfg-st');st.style.display='block';st.style.color='var(--accent6)';st.textContent='❌ '+(d.message||'失败');}
      }).catch(function(e){var st=$('cfg-st');st.style.display='block';st.style.color='var(--accent6)';st.textContent='❌ '+e.message;});
  },
};

// ══════════════════════════════════════════════════
// INIT
// ══════════════════════════════════════════════════
function init(){
  ib.addEventListener('input',function(){this.style.height='auto';this.style.height=Math.min(this.scrollHeight,100)+'px'});
  ib.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});

  document.querySelectorAll('.p-tab').forEach(function(t){
    t.addEventListener('click',function(){
      document.querySelectorAll('.p-tab,.p-content').forEach(function(x){x.classList.remove('active')});
      t.classList.add('active');$('pn-'+t.dataset.t).classList.add('active');
    });
  });

  buildTools();renderEvFilters();buildConfig();
  connectSSE();
  setTimeout(function(){$('loading').classList.add('hidden')},500);
  setTimeout(function(){addSys('⚡ ClaudeZ v2 · 动态提示词驱动的自主 AI 智能体');toast('🎉 欢迎使用 ClaudeZ','success');},800);
}

if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();

})();
