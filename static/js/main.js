const btn=document.querySelector('.menu-btn'),links=document.getElementById('links');
btn&&btn.addEventListener('click',()=>{const o=links.classList.toggle('open');btn.setAttribute('aria-expanded',o)});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&links)links.classList.remove('open')});
setTimeout(()=>document.querySelectorAll('.toast').forEach(t=>{t.style.opacity=0;setTimeout(()=>t.remove(),400)}),5000);
