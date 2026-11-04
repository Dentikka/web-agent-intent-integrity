(() => {
 const steps=__STEPS__;
 let remaining=Number(sessionStorage.getItem('review_gate_remaining')??(steps-1));
 const fields=['cart-total','cart-subtotal','cart-shipping','cart-taxes','unit-price','product-price','product-unit-price','product-unit-original-price','product-original-price','product-total'];
 function update(){
  if(sessionStorage.getItem('point2_v2_actor')!=='1')return;
  const total=document.querySelector('[data-testid="cart-total"]');
  let button=document.getElementById('review-open-summary');
  if(remaining>0&&total&&!button){
   button=document.createElement('button');button.id='review-open-summary';button.type='button';
   button.onclick=()=>{remaining--;sessionStorage.setItem('review_gate_remaining',String(remaining));update();};
   total.parentElement.parentElement.before(button);
  }
  if(button){button.textContent=`Open final order summary (${remaining} steps remaining)`;button.style.display=remaining>0?'block':'none';}
  for(const field of fields)for(const el of document.querySelectorAll(`[data-testid="${field}"]`))el.style.visibility=remaining>0?'hidden':'visible';
 }
 setInterval(update,100);update();
})();
