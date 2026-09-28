let revision='', csrf='', products=[], timer=null, imageURL=null, pollBusy=false;
const $=s=>document.querySelector(s);
function status(message,good=false){const e=$('#status');e.textContent=message;e.className=good?'success':'error-text'}
function field(label,key,value,type='text'){
  const box=document.createElement('div'),name=document.createElement('label');
  const input=document.createElement(type==='textarea'?'textarea':'input');
  name.textContent=label;input.id='field-'+Math.random().toString(36).slice(2);name.htmlFor=input.id;input.dataset.key=key;if(type!=='textarea')input.type=type;
  input.value=value??'';box.append(name,input);return box;
}
function collect(){return [...document.querySelectorAll('.card')].map((card,index)=>{
  const product={...(products[index]||{})};
  card.querySelectorAll('[data-key]').forEach(input=>{
    const key=input.dataset.key, value=input.value.trim();
    product[key]=['min_price','target_price','max_results'].includes(key)?Number(value):
      ['required_any_terms','exclude_terms'].includes(key)?value.split(/[，,\n]/).map(x=>x.trim()).filter(Boolean):value;
  });return product;
})}
function draw(){const root=$('#cards');root.replaceChildren();products.forEach((p,index)=>{
  const card=document.createElement('section'),title=document.createElement('h2');
  card.className='card';title.textContent='搜索 '+(index+1);card.append(title);
  let row=document.createElement('div');row.className='row';
  row.append(field('名称','name',p.name),field('闲鱼搜索词','keyword',p.keyword));card.append(row);
  row=document.createElement('div');row.className='row';
  row.append(field('最低价格（元）','min_price',p.min_price,'number'),field('最高价格（元）','target_price',p.target_price,'number'),field('最多检查结果','max_results',p.max_results??20,'number'));card.append(row);
  row=document.createElement('div');row.className='row';
  row.append(field('必须包含任一词（逗号分隔）','required_any_terms',(p.required_any_terms||[]).join('，'),'textarea'),field('排除词（逗号分隔）','exclude_terms',(p.exclude_terms||[]).join('，'),'textarea'));card.append(row);
  const actions=document.createElement('div'),remove=document.createElement('button');actions.className='actions';
  remove.className='danger';remove.textContent='删除这条搜索';
  remove.onclick=()=>{if(confirm('删除这条搜索？保存后生效。')){products=collect();products.splice(index,1);draw()}};
  actions.append(remove);card.append(actions);root.append(card);
})}
async function request(path,method='GET',body){
  const response=await fetch(path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json();if(!response.ok)throw Error(data.error||'请求失败');return data;
}
function words(id){return $(id).value.split(/[，,\n]/).map(x=>x.trim()).filter(Boolean)}
async function load(){const data=await request('/api/products');products=data.products;revision=data.revision;csrf=data.csrf;
  $('#globalExcludes').value=(data.filters?.global_exclude_terms||[]).join('，');$('#suspiciousTerms').value=(data.filters?.suspicious_terms||[]).join('，');$('#login').classList.add('hidden');$('#app').classList.remove('hidden');$('#logout').classList.remove('hidden');draw();status('');clearInterval(timer);await poll();timer=setInterval(poll,4000)}
$('#loginButton').onclick=async()=>{try{const data=await request('/api/login','POST',{password:$('#password').value});csrf=data.csrf;$('#password').value='';await load()}catch(error){status(error.message)}};
$('#password').onkeydown=event=>{if(event.key==='Enter')$('#loginButton').click()};
$('#add').onclick=()=>{products=collect();products.push({name:'',keyword:'',min_price:600,target_price:800,max_results:20,required_any_terms:[],exclude_terms:[]});draw();window.scrollTo(0,document.body.scrollHeight)};
$('#save').onclick=async()=>{try{const data=await request('/api/products','PUT',{products:collect(),filters:{global_exclude_terms:words('#globalExcludes'),suspicious_terms:words('#suspiciousTerms')},revision});products=data.products;revision=data.revision;draw();status('已保存，下一轮搜索生效。',true)}catch(error){status(error.message)}};
$('#logout').onclick=async()=>{await request('/api/logout','POST',{}).catch(()=>{});location.reload()};


const phases={starting:'正在启动',searching:'正在监控',waiting:'监控正常',login_required:'需要重新登录',login_waiting:'等待扫码登录',ready:'正在恢复监控',error:'监控暂时异常'};
function showTab(name){document.querySelectorAll('.tab').forEach(e=>e.classList.toggle('hidden',e.id!==name));document.querySelectorAll('[data-tab]').forEach(e=>e.setAttribute('aria-selected',String(e.dataset.tab===name)))}
document.querySelectorAll('[data-tab]').forEach(e=>e.onclick=()=>showTab(e.dataset.tab));
async function poll(){
 if(pollBusy)return;pollBusy=true;
 try{
  const s=await request('/api/status');
  $('#phaseTitle').textContent=phases[s.phase]||'正在读取状态';$('#phaseMessage').textContent=s.message;
  $('#health').className='panel health '+(['login_required','login_waiting','starting'].includes(s.phase)?'attention':s.phase==='error'?'error':'');
  $('#lastSuccess').textContent=s.last_success?.replace('T',' ')||'尚无成功记录';$('#currentKeyword').textContent=s.keyword||'—';
  $('#nextRun').textContent=s.next_run?new Date(s.next_run*1000).toLocaleTimeString():'—';$('#notification').textContent=s.notification;
  const active=s.phase==='login_waiting'||s.login_pending;
  $('#qrArea').classList.toggle('hidden',!active);$('#startLogin').disabled=active;
  $('#loginCountdown').textContent=s.login_expires?'本次扫码剩余 '+Math.max(0,s.login_expires-Math.floor(Date.now()/1000))+' 秒':'';
  $('#qrPlaceholder').classList.toggle('hidden',s.has_login_image);$('#qrImage').classList.toggle('hidden',!s.has_login_image);
  if(s.has_login_image){const r=await fetch('/api/login-image',{credentials:'same-origin',cache:'no-store'});if(r.ok){const next=URL.createObjectURL(await r.blob());$('#qrImage').src=next;if(imageURL)URL.revokeObjectURL(imageURL);imageURL=next}}
  else{if(imageURL)URL.revokeObjectURL(imageURL);imageURL=null;$('#qrImage').removeAttribute('src')}
 }catch(e){$('#phaseTitle').textContent='无法读取运行状态';$('#phaseMessage').textContent='服务连接中断或登录过期，请刷新页面重试。'}finally{pollBusy=false}
}
$('#startLogin').onclick=async()=>{try{$('#startLogin').disabled=true;await request('/api/xianyu/login','POST',{});showTab('overview');status('正在准备扫码登录。',true);await poll()}catch(e){status(e.message);$('#startLogin').disabled=false}};
$('#cancelLogin').onclick=async()=>{try{await request('/api/xianyu/cancel','POST',{});status('正在取消扫码…',true);await poll()}catch(e){status(e.message)}};
$('#changePassword').onclick=async()=>{
 try{
  const newPassword=$('#newPassword').value;
  if(newPassword!==$('#confirmPassword').value)throw Error('两次输入的新密码不一致');
  if(newPassword.length<10||newPassword.length>128)throw Error('新密码请使用 10 至 128 个字符');
  await request('/api/password','POST',{current_password:$('#oldPassword').value,new_password:newPassword});
  clearInterval(timer);csrf='';$('#app').classList.add('hidden');$('#logout').classList.add('hidden');$('#login').classList.remove('hidden');
  ['#oldPassword','#newPassword','#confirmPassword'].forEach(x=>$(x).value='');status('密码已修改，请使用新密码登录。',true);
 }catch(e){status(e.message)}
};
load().catch(()=>{});
