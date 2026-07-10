"""
數據看板 Web 頁面 - 手機優先卡片式版面
"""
DASHBOARD_HTML = r'''<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>投資客案件收集器</title>
<style>
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang TC","Microsoft JhengHei",sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;padding-bottom:16px}
.header{position:sticky;top:0;z-index:10;background:#1e293b;border-bottom:1px solid #334155;padding:12px 16px;display:flex;justify-content:space-between;align-items:center}
.header h1{font-size:17px;font-weight:700;color:#f8fafc}
.header .refresh{background:#3b82f6;color:white;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600}
.header .refresh:active{background:#2563eb}
.stats{display:flex;gap:8px;padding:12px 16px;overflow-x:auto;scrollbar-width:none}
.stats::-webkit-scrollbar{display:none}
.stat-card{flex:0 0 auto;min-width:80px;background:#1e293b;border-radius:8px;padding:10px 14px;border:1px solid #334155;text-align:center}
.stat-card .value{font-size:22px;font-weight:700;color:#f8fafc;line-height:1.2}
.stat-card .label{font-size:11px;color:#94a3b8;margin-top:2px}
.stat-card.warn .value{color:#f59e0b}
.controls{padding:0 16px 8px;display:flex;gap:6px;flex-wrap:wrap}
.controls select,.controls input{background:#1e293b;border:1px solid #475569;color:#e2e8f0;padding:8px 10px;border-radius:6px;font-size:13px}
.controls select{appearance:none;-webkit-appearance:none;padding-right:24px;background-image:url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'12\' height=\'12\' viewBox=\'0 0 12 12\'%3E%3Cpath fill=\'%2394a3b8\' d=\'M6 8L1 3h10z\'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 6px center}
.controls input[type=text]{flex:1;min-width:120px}
.loading{text-align:center;padding:60px 20px;color:#64748b;font-size:14px}
.listing-grid{padding:0 16px;display:flex;flex-direction:column;gap:10px}
.listing-card{background:#1e293b;border-radius:10px;border:1px solid #334155;overflow:hidden;transition:opacity .2s}
.listing-card.processed{opacity:.5}
.card-main{padding:12px;cursor:pointer}
.card-row{display:flex;align-items:flex-start;gap:10px}
.card-img{flex-shrink:0;width:80px;height:80px;border-radius:6px;overflow:hidden;background:#0f172a}
.card-img img{width:100%;height:100%;object-fit:cover;cursor:pointer}
.card-img .no-img{width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:#475569;font-size:11px}
.card-info{flex:1;min-width:0}
.card-info .tags{display:flex;gap:6px;align-items:center;margin-bottom:6px;flex-wrap:wrap}
.tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}
.tag-sale{background:#065f46;color:#6ee7b7}
.tag-rent{background:#1e3a5f;color:#93c5fd}
.tag-sold{background:#7c2d12;color:#fdba74}
.tag-price-drop{background:#78350f;color:#fbbf24}
.card-info .address{font-size:14px;font-weight:600;color:#f8fafc;line-height:1.4;margin-bottom:4px;word-break:break-all}
.card-info .sub{font-size:12px;color:#94a3b8;line-height:1.5}
.card-info .price{font-size:16px;font-weight:700;color:#f87171;margin-top:4px}
.card-info .contact-row{font-size:11px;color:#64748b;margin-top:4px;line-height:1.5;word-break:break-all}
.quality-dots{display:flex;gap:4px;margin-top:6px}
.quality-dot{width:8px;height:8px;border-radius:50%}
.quality-dot.ok{background:#22c55e}
.quality-dot.miss{background:#475569}
.card-detail{display:none;padding:0 12px 12px;border-top:1px solid #334155;margin-top:8px;padding-top:8px;font-size:12px;color:#94a3b8;line-height:1.6;white-space:pre-wrap;word-break:break-all}
.card-detail.show{display:block}
.card-actions{display:flex;border-top:1px solid #334155}
.card-actions button{flex:1;border:none;background:transparent;color:#94a3b8;font-size:13px;font-weight:600;padding:10px 6px;cursor:pointer}
.card-actions button:active{background:rgba(255,255,255,.05)}
.card-actions button.processed{background:#065f46;color:#6ee7b7}
.card-actions button.unprocessed{color:#fdba74}
.table-wrap{display:none}
@media (min-width:768px){
.stats{justify-content:center}
.listing-grid{display:none !important}
.table-wrap{display:block;padding:0 24px 24px;overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#1e293b;color:#94a3b8;font-weight:600;padding:10px 12px;text-align:left;border-bottom:1px solid #334155;position:sticky;top:0;z-index:1}
td{padding:8px 12px;border-bottom:1px solid #1e293b;vertical-align:middle}
tr:hover{background:#1e293b50}
tr.row-processed{opacity:.55}
.thumb{max-width:60px;max-height:60px;border-radius:4px;cursor:pointer;object-fit:cover}
.thumb:hover{transform:scale(3);position:relative;z-index:99;box-shadow:0 4px 20px rgba(0,0,0,.6)}
.no-img{color:#334155;font-size:11px;text-align:center;display:inline-block;width:60px}
.contact-cell{font-size:11px;line-height:1.5;max-width:150px;word-break:break-all}
.status-btn{border:none;padding:4px 12px;border-radius:14px;font-size:12px;font-weight:600;cursor:pointer;white-space:nowrap}
.status-btn.unprocessed{background:#7c2d12;color:#fdba74}
.status-btn.unprocessed:hover{background:#9a3412}
.status-btn.processed{background:#065f46;color:#6ee7b7}
.status-btn.processed:hover{background:#047857}
}
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
<option value="price_drop">降價</option>
</select>
<input type="text" id="filterAddress" placeholder="搜尋地址..." oninput="debounce(loadData,300)()">
</div>
<div id="loading" class="loading">載入中...</div>
<div class="table-wrap" id="tableWrap">
<table id="table">
<thead><tr>
<th>狀態</th><th>圖片</th><th>品質</th><th>類型</th><th>地址</th><th>格局</th><th>坪數</th><th>價格</th><th>時間</th><th>聯絡資訊</th>
</tr></thead>
<tbody id="tbody"></tbody>
</table>
</div>
<div class="listing-grid" id="listingGrid"></div>
<div id="preview" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.9);z-index:999;justify-content:center;align-items:center;padding:16px" onclick="this.style.display=\'none\'">
<img id="previewImg" style="max-width:100%;max-height:90vh;border-radius:8px;object-fit:contain">
</div>
<script>
const PTYPES={"apartment":"電梯大樓","condo":"公寓","house":"透天/別墅","studio":"套房","office":"店面/商辦","land":"土地","parking":"車位"};
var TOKEN = new URLSearchParams(location.search).get("token") || "";

async function loadData(){
document.getElementById(\'loading\').style.display=\'block\';
document.getElementById(\'tableWrap\').style.display=\'none\';
document.getElementById(\'listingGrid\').style.display=\'none\';
const processed=document.getElementById(\'filterProcessed\').value;
var params=new URLSearchParams({type:document.getElementById(\'filterType\').value,category:document.getElementById(\'filterCategory\').value,address:document.getElementById(\'filterAddress\').value,limit:100});
if(processed!==\'\')params.set(\'processed\',processed);
if(TOKEN)params.set(\'token\',TOKEN);
const res=await fetch(\'/api/listings?\'+params);
const data=await res.json();
renderStats(data);
const isMobile=window.innerWidth<768;
if(isMobile){renderCards(data.results);document.getElementById(\'listingGrid\').style.display=\'flex\';}
else{renderTable(data.results);document.getElementById(\'tableWrap\').style.display=\'block\';}
document.getElementById(\'loading\').style.display=\'none\';
}

function qualityDots(l){
var s=\'<div class="quality-dots">\';
s+=\'<span class="quality-dot \'+(l.has_address?\'ok\':\'miss\')+\'" title="地址"></span>\';
s+=\'<span class="quality-dot \'+(l.has_price?\'ok\':\'miss\')+\'" title="價格"></span>\';
s+=\'<span class="quality-dot \'+(l.has_contact?\'ok\':\'miss\')+\'" title="聯絡"></span>\';
s+=\'</div>\';
return s;
}

function renderStats(data){
const listings=data.results||[];
const sale=listings.filter(l=>l.listing_type===\'sale\'&&l.category!==\'sold\');
const sold=listings.filter(l=>l.category===\'sold\');
const rent=listings.filter(l=>l.listing_type===\'rent\');
const unprocessed=listings.filter(l=>!l.is_processed);
const totalPrice=sale.reduce((s,l)=>s+(l.price_wan||0),0);
const avgPrice=sale.length?Math.round(totalPrice/sale.length):0;
document.getElementById(\'stats\').innerHTML=
\'<div class="stat-card warn"><div class="value">\'+unprocessed.length+\'</div><div class="label">未處理</div></div>\'+
\'<div class="stat-card"><div class="value">\'+data.total+\'</div><div class="label">總案件</div></div>\'+
\'<div class="stat-card"><div class="value">\'+sale.length+\'</div><div class="label">出售 | \'+avgPrice+\'萬</div></div>\'+
\'<div class="stat-card"><div class="value">\'+rent.length+\'</div><div class="label">出租</div></div>\'+
\'<div class="stat-card"><div class="value">\'+sold.length+\'</div><div class="label">已成交</div></div>\';
}

function renderCards(listings){
const grid=document.getElementById(\'listingGrid\');
grid.innerHTML=listings.map(function(l){
const tf=function(v,f){if(v==null||isNaN(v))return\'\';return f(v);};
const typeTag=l.listing_type===\'rent\'?\'tag-rent\':(l.category===\'sold\'?\'tag-sold\':(l.category===\'price_drop\'?\'tag-price-drop\':\'tag-sale\'));
const typeLabel=l.listing_type===\'rent\'?\'出租\':(l.category===\'sold\'?\'已售\':(l.category===\'price_drop\'?\'降價\':\'出售\'));
const ptype=PTYPES[l.property_type]||l.property_type||\'\';
var price=\'\';
if(l.price_wan){
if(l.listing_type===\'rent\')price=\'月租 \'+l.price_wan.toFixed(1)+\' 萬\';
else if(l.category===\'price_drop\'&&l.old_price_wan)price=l.old_price_wan.toFixed(0)+\' 萬 \\\\u2192 \'+l.price_wan.toFixed(0)+\' 萬\';
else price=Math.round(l.price_wan)+\' 萬\';
}
var subParts=[];
if(ptype)subParts.push(ptype);
if(l.rooms)subParts.push(l.rooms);
if(l.floor)subParts.push(l.floor+\'F\');
if(l.size_ping)subParts.push(l.size_ping+\'坪\');
if(l.community)subParts.push(l.community);
var sub=subParts.join(\'  \');
var contactParts=[];
if(l.contact_name)contactParts.push(l.contact_name);
if(l.contact_phone)contactParts.push(l.contact_phone);
if(l.contact_line)contactParts.push(\'LINE: \'+l.contact_line);
var contact=contactParts.length?contactParts.join(\' | \'):\'\';
var imgHtml=l.image_url
?\'<img src="\'+l.image_url+\'" onclick="event.stopPropagation();showPreview(\\\'\'+l.image_url+\'\\\')" onerror="this.parentElement.innerHTML=\\\'<span class=no-img>-</span>\\\'">\'
:\'<span class="no-img">-</span>\';
var isP=l.is_processed;
var desc=l.description||\'\';
var detailHtml=desc?\'<div class="card-detail" id="detail-\'+l.id+\'">\'+escHtml(desc)+\'</div>\':\'\';
return \'<div class="listing-card\'+(isP?\' processed\':\'\')+\'" id="card-\'+l.id+\'">\'+
\'<div class="card-main" onclick="toggleDetail(\'+l.id+\')">\'+
\'<div class="card-row">\'+
\'<div class="card-img">\'+imgHtml+\'</div>\'+
\'<div class="card-info">\'+
\'<div class="tags"><span class="tag \'+typeTag+\'">\'+typeLabel+\'</span></div>\'+
\'<div class="address">\'+(l.address||\'無地址\')+\'</div>\'+
(sub?\'<div class="sub">\'+sub+\'</div>\':\'\')+
(price?\'<div class="price">\'+price+\'</div>\':\'\')+
(contact?\'<div class="contact-row">\'+contact+\'</div>\':\'\')+
qualityDots(l)+
\'</div></div>\'+detailHtml+\'</div>\'+
\'<div class="card-actions">\'+
\'<button class="\'+(isP?\'processed\':\'unprocessed\')+\'" onclick="toggleStatus(\'+l.id+\',this)">\'+(isP?\'已處理\':\'未處理\')+\'</button>\'+
\'</div>\'+
\'</div>\';
}).join(\'\');
}

function renderTable(listings){
const tbody=document.getElementById(\'tbody\');
tbody.innerHTML=listings.map(function(l){
const tf=function(v,f){if(v==null||isNaN(v))return\'\';return f(v);};
const typeTag=l.listing_type===\'rent\'?\'tag-rent\':(l.category===\'sold\'?\'tag-sold\':(l.category===\'price_drop\'?\'tag-price-drop\':\'tag-sale\'));
const typeLabel=l.listing_type===\'rent\'?\'出租\':(l.category===\'sold\'?\'已售\':(l.category===\'price_drop\'?\'降價\':\'出售\'));
const ptype=PTYPES[l.property_type]||l.property_type||\'\';
var price=\'\';
if(l.price_wan){
if(l.listing_type===\'rent\')price=\'月租 \'+l.price_wan.toFixed(1)+\'萬\';
else price=Math.round(l.price_wan)+\'萬\';
}
var imgCell=l.image_url
?\'<img src="\'+l.image_url+\'" class="thumb" onclick="event.stopPropagation();showPreview(\\\'\'+l.image_url+\'\\\')" onerror="this.outerHTML=\\\'<span class=no-img>-</span>\\\'">\'
:\'<span class="no-img">-</span>\';
var contactParts=[l.contact_name||\'\',l.contact_phone||\'\',l.contact_line?\'LINE: \'+l.contact_line:\'\'].filter(Boolean);
var contact=contactParts.length?contactParts.join(\'<br>\'):\'<span style="color:#475569">-</span>\';
var isP=l.is_processed;
return \'<tr class="\'+(isP?\'row-processed\':\'\')+\'" id="row-\'+l.id+\'">\'+
\'<td><button class="status-btn \'+(isP?\'processed\':\'unprocessed\')+\'" onclick="toggleStatus(\'+l.id+\',this)">\'+(isP?\'已處理\':\'未處理\')+\'</button></td>\'+
\'<td style="width:70px">\'+imgCell+\'</td>\'+
\'<td>\'+qualityDots(l).replace(\'quality-dots\',\'quality-dots" style="justify-content:center\')+\'</td>\'+
\'<td><span class="tag \'+typeTag+\'">\'+typeLabel+\'</span><br><span style="color:#94a3b8;font-size:11px">\'+ptype+\'</span></td>\'+
\'<td>\'+(l.address||\'-\')+(l.community?\'<br><span style="color:#64748b;font-size:11px">\'+l.community+\'</span>\':\'\')+\'</td>\'+
\'<td>\'+(l.rooms||\'-\')+\'</td>\'+
\'<td>\'+(l.size_ping?l.size_ping+\'坪\':\'-\')+\'</td>\'+
\'<td class="price">\'+(price||\'-\')+\'</td>\'+
\'<td style="color:#94a3b8;white-space:nowrap;font-size:12px">\'+((l.posted_at||\'\').slice(0,10))+\'</td>\'+
\'<td class="contact-cell">\'+contact+\'</td>\'+
\'</tr>\';
}).join(\'\');
}

function toggleDetail(id){
var el=document.getElementById(\'detail-\'+id);
if(el)el.classList.toggle(\'show\');
}

function escHtml(s){return s.replace(/&/g,\'&amp;\').replace(/</g,\'&lt;\').replace(/>/g,\'&gt;\');}

async function toggleStatus(id,el){
el.disabled=true;
var original=el.textContent;el.textContent=\'...\';
try{await fetch(\'/api/listings/\'+id+\'/toggle-processed\',{method:\'POST\'});loadData();}
catch(e){el.textContent=original;}
finally{el.disabled=false}
}

function showPreview(url){
document.getElementById(\'previewImg\').src=url;
document.getElementById(\'preview\').style.display=\'flex\';
}

var timer;
function debounce(fn,ms){return function(){clearTimeout(timer);timer=setTimeout(fn,ms);}}
window.addEventListener(\'resize\',loadData);
loadData();
setInterval(loadData,30000);
</script>
</body>
</html>'''
