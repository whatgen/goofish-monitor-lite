let revision='', csrf='', products=[];
const $=s=>document.querySelector(s);
function status(message,good=false){const e=$('#status');e.textContent=message;e.className=good?'success':'error'}
function field(label,key,value,type='text'){
  const box=document.createElement('div'),name=document.createElement('label');
  const input=document.createElement(type==='textarea'?'textarea':'input');
  name.textContent=label;input.dataset.key=key;if(type!=='textarea')input.type=type;
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
async function load(){const data=await request('/api/products');products=data.products;revision=data.revision;csrf=data.csrf;
  $('#login').classList.add('hidden');$('#app').classList.remove('hidden');draw();status('')}
$('#loginButton').onclick=async()=>{try{const data=await request('/api/login','POST',{password:$('#password').value});csrf=data.csrf;$('#password').value='';await load()}catch(error){status(error.message)}};
$('#password').onkeydown=event=>{if(event.key==='Enter')$('#loginButton').click()};
$('#add').onclick=()=>{products=collect();products.push({name:'',keyword:'',min_price:600,target_price:800,max_results:20,required_any_terms:[],exclude_terms:[]});draw();window.scrollTo(0,document.body.scrollHeight)};
$('#save').onclick=async()=>{try{const data=await request('/api/products','PUT',{products:collect(),revision});products=data.products;revision=data.revision;draw();status('已保存，下一轮搜索生效。',true)}catch(error){status(error.message)}};
$('#logout').onclick=async()=>{await request('/api/logout','POST',{}).catch(()=>{});location.reload()};
load().catch(()=>{});
