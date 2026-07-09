"""
數據看板 Web 頁面 - 含已處理/未處理切換
"""
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>投資客案件收集器</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}
.header{background:#1e293b;border-bottom:1px solid #334155;padding:16px 24px;display:flex;justify-content:space-between;align-items:center}
.header h1{font-size:20px;color:#f8fafc}
.header .refresh{background:#3b82f6;color:white;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;font-size:14px}
.header .refresh:hover{background:#2563eb}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;padding:20px 24px}
.stat-card{background:#1e293b;border-radius:10px;padding:16px;border:1px solid #334155}
.stat-card .label{font-size:12px;color:#94a3b8;margin-bottom:4px}
.stat-card .value{font-size:26px;font-weight:700;color:#f8fafc}
.stat-card .sub{font-size:12px;color:#64748b;margin-top:4px}
.stat-card.warn .value{color:#f59e0b}
.controls{padding:0 24px 12px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.controls select,.controls input{background:#1e293b;border:1px solid #475569;color:#e2e8f0;padding:6px 12px;border-radius:6px;font-size:13px}
.controls input[type=text]{width:200px}
.table-wrap{padding:0 24px 24px;overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#1e293b;color:#94a3b8;font-weight:600;padding:10px 12px;text-align:left;border-bottom:1px solid #334155;position:sticky;top:0;z-index:1}
td{padding:8px 12px;border-bottom:1px solid #1e293b;vertical-align:middle}
tr:hover{background:#1e293b50}
tr.row-processed{opacity:.55}
.tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}
.tag-sale{background:#065f46;color:#6ee7b7}
.tag-rent{background:#1e3a5f;color:#93c5fd}
.tag-sold{background:#7c2d12;color:#fdba74}
.price{font-weight:600;color:#f8fafc;white-space:nowrap}
.loading{text-align:center;padding:40px;color:#64748b}
.hidden{display:none}
.thumb{max-width:60px;max-height:60px;border-radius:4px;cursor:pointer;transition:transform .2s;object-fit:cover}
.thumb:hover{transform:scale(3);position:relative;z-index:99;box-shadow:0 4px 20px rgba(0,0,0,.6)}
.contact-cell{font-size:11px;line-height:1.5;max-width:150px;word-break:break-all}
.no-img{color:#334155;font-size:11px;text-align:center;display:inline-block;width:60px}
.status-btn{border:none;padding:4px 12px;border-radius:14px;font-size:12px;font-weight:600;cursor:pointer;white-space:nowrap;transition:all .15s}
.status-btn.unprocessed{background:#7c2d12;color:#fdba74}
.status-btn.unprocessed:hover{background:#9a3412}
.status-btn.processed{background:#065f46;color:#6ee7b7}
.status-btn.processed:hover{background:#047857}
</style>
</head>
<body>
<div class="header">
<h1>投資客案件收集器</h1>
<button class="refresh" onclick="loadData()">重新整理</button>
</div>
<div class="stats" id="stats"></div>
<div class="controls">
<select id="filterProcessed" onchange="loadData()">
<option value="">全部狀態</option>
<option value="false" selected>未處理</option>
<option value="true">已處理</option>
</select>
<select id="filterType" onchange="loadData()">
<option value="">全部類型</option>
<option value="sale">出售</option>
<option value="rent">出租</option>
</select>
<select id="filterCategory" onchange="loadData()">
<option value="">全部分類</option>
<option value="new_listing">新案件</option>
<option value="sold">已成交</option>
</select>
<select id="filterProperty" onchange="loadData()">
<option value="">全部物件</option>
<option value="apartment">電梯大樓</option>
<option value="condo">公寓</option>
<option value="house">透天/別墅</option>
<option value="studio">套房</option>
<option value="office">店面/商辦</option>
<option value="land">土地</option>
<option value="parking">車位</option>
</select>
<input type="text" id="filterAddress" placeholder="搜尋地址..." oninput="debounce(loadData,300)()">
</div>
<div class="table-wrap">
<div id="loading" class="loading">載入中...</div>
<table id="table" class="hidden">
<thead><tr>
<th>狀態</th><th>圖片</th><th>類型</th><th>地址</th><th>格局</th><th>坪數</th><th>價格</th><th>時間</th><th>聯絡資訊</th>
</tr></thead>
<tbody id="tbody"></tbody>
</table>
</div>
<div id="preview" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.85);z-index:999;justify-content:center;align-items:center" onclick="this.style.display='none'">
<img id="previewImg" style="max-width:90vw;max-height:90vh;border-radius:8px;box-shadow:0 0 40px rgba(0,0,0,.8)">
</div>
<script>
const PTYPES={"apartment":"大樓","condo":"公寓","house":"透天","studio":"套房","office":"店面","land":"土地","parking":"車位"};

async function loadData(){
document.getElementById('loading').classList.remove('hidden');
document.getElementById('table').classList.add('hidden');
const processed=document.getElementById('filterProcessed').value;
const params=new URLSearchParams({
type:document.getElementById('filterType').value,
category:document.getElementById('filterCategory').value,
property:document.getElementById('filterProperty').value,
address:document.getElementById('filterAddress').value,
limit:100
});
if(processed!=='')params.set('processed',processed);
const res=await fetch('/api/listings?'+params);
const data=await res.json();
renderStats(data);
renderTable(data.results);
document.getElementById('loading').classList.add('hidden');
document.getElementById('table').classList.remove('hidden');
}

function renderStats(data){
const listings=data.results||[];
const sale=listings.filter(l=>l.listing_type==='sale'&&l.category!=='sold');
const sold=listings.filter(l=>l.category==='sold');
const rent=listings.filter(l=>l.listing_type==='rent');
const unprocessed=listings.filter(l=>!l.is_processed);
const totalPrice=sale.reduce((s,l)=>s+(l.price_wan||0),0);
const avgPrice=sale.length?Math.round(totalPrice/sale.length):0;
document.getElementById('stats').innerHTML=`
<div class="stat-card warn"><div class="label">未處理</div><div class="value">${unprocessed.length}</div></div>
<div class="stat-card"><div class="label">總案件</div><div class="value">${data.total}</div></div>
<div class="stat-card"><div class="label">出售中</div><div class="value">${sale.length}</div><div class="sub">均價 ${avgPrice} 萬</div></div>
<div class="stat-card"><div class="label">出租中</div><div class="value">${rent.length}</div></div>
<div class="stat-card"><div class="label">已成交</div><div class="value">${sold.length}</div></div>
`;
}

function renderTable(listings){
const tbody=document.getElementById('tbody');
tbody.innerHTML=listings.map(l=>{
const typeTag=l.listing_type==='rent'?'tag-rent':(l.category==='sold'?'tag-sold':'tag-sale');
const typeLabel=l.listing_type==='rent'?'出租':(l.category==='sold'?'已售':'出售');
const ptype=PTYPES[l.property_type]||l.property_type||'';
const price=l.price_wan?l.listing_type==='rent'?`月租 ${l.price_wan.toFixed(1)}萬`:`${Math.round(l.price_wan)}萬`:'';
const imgCell=l.image_url
?`<img src="${l.image_url}" class="thumb" onclick="event.stopPropagation();showPreview('${l.image_url}')" onerror="this.outerHTML='<span class=&quot;no-img&quot;>-</span>'">`
:'<span class="no-img">-</span>';
const contactParts=[
l.contact_name||'',
l.contact_phone?'📞 '+l.contact_phone:'',
l.contact_line?'LINE: '+l.contact_line:'',
l.contact_agency||''
].filter(Boolean);
const contact=contactParts.length?contactParts.join('<br>'):'<span style="color:#475569">-</span>';
const isP=l.is_processed;
const btnClass=isP?'processed':'unprocessed';
const btnLabel=isP?'已處理':'未處理';
const rowClass=l.is_processed?'row-processed':'';
return '<tr class="'+rowClass+'" id="row-'+l.id+'">'+
'<td><button class="status-btn '+btnClass+'" onclick="toggleStatus('+l.id+',this)">'+btnLabel+'</button></td>'+
'<td style="width:70px">'+imgCell+'</td>'+
'<td><span class="tag '+typeTag+'">'+typeLabel+'</span><br><span style="color:#94a3b8;font-size:11px">'+ptype+'</span></td>'+
'<td>'+(l.address||'-')+(l.community?'<br><span style="color:#64748b;font-size:11px">'+l.community+'</span>':'')+'</td>'+
'<td>'+(l.rooms||'-')+'</td>'+
'<td>'+(l.size_ping?l.size_ping+'坪':'-')+'</td>'+
'<td class="price">'+(price||'-')+'</td>'+
'<td style="color:#94a3b8;white-space:nowrap;font-size:12px">'+((l.posted_at||'').slice(0,10))+'</td>'+
'<td class="contact-cell">'+contact+'</td>'+
'</tr>';
}).join('');
}

async function toggleStatus(id,btn){
btn.disabled=true;
btn.textContent='...';
try{
const res=await fetch('/api/listings/'+id+'/toggle-processed',{method:'POST'});
const data=await res.json();
const isP=data.is_processed;
btn.className='status-btn '+(isP?'processed':'unprocessed');
btn.textContent=isP?'已處理':'未處理';
const row=document.getElementById('row-'+id);
if(row)row.className=isP?'row-processed':'';
loadData();
}catch(e){
alert('操作失敗');
}finally{
btn.disabled=false;
}
}

function showPreview(url){
document.getElementById('previewImg').src=url;
document.getElementById('preview').style.display='flex';
}

let timer;
function debounce(fn,ms){return function(){clearTimeout(timer);timer=setTimeout(fn,ms);}}

loadData();
setInterval(loadData,30000);
</script>
</body>
</html>"""
