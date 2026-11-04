(() => {
 const steps=__STEPS__;
 let remaining=Number(sessionStorage.getItem('review_gate_remaining')??(steps-1));
 const hidden=new Map();
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
  if(remaining>0){
   const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);const found=[];
   while(walker.nextNode()){
    const node=walker.currentNode;const el=node.parentElement;
    if(!el||el.closest('[data-review-preserved-label]')||['SCRIPT','STYLE'].includes(el.tagName))continue;
    if(/€\s*\d/.test(node.textContent)&&getComputedStyle(el).visibility!=='hidden')found.push(el);
   }
   for(const el of found){
    if(hidden.has(el))continue;
    const label=el.textContent.replace(/€\s*[\d.,]+/g,'').trim();
    const clone=document.createElement('span');clone.dataset.reviewPreservedLabel='1';clone.textContent=label;
    clone.style.visibility='visible';el.append(clone);hidden.set(el,clone);
   }
  }
  for(const [el,clone] of hidden){el.style.visibility=remaining>0?'hidden':'visible';clone.style.display=remaining>0?'inline':'none';}

 }
 setInterval(update,100);update();
})();
