const EYE='<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
      OFF='<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM4 4l16 16"/><circle cx="12" cy="12" r="3"/>';
document.querySelectorAll('.eye').forEach(b=>b.addEventListener('click',()=>{
  const i=b.parentElement.querySelector('input'),show=i.type==='password';
  i.type=show?'text':'password';b.setAttribute('aria-label',show?'Hide password':'Show password');b.querySelector('svg').innerHTML=show?EYE:OFF;}));
const f=document.getElementById('auth-form');
f&&f.addEventListener('submit',e=>{
  const bad=[...f.querySelectorAll('input[required]')].find(i=>!i.value.trim()||(i.type==='email'&&!i.checkValidity())||(i.minLength>0&&i.value.length<i.minLength));
  if(bad){e.preventDefault();bad.focus();bad.reportValidity();}});
