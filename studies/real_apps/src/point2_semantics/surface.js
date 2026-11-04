// All observations come from the actual application callbacks. Only explicit
// representation transforms are applied, with no inserted false values.
(() => {
  const app=__APP__, cfg=__CONFIG__;
  const mc=document.modelContext??navigator.modelContext;
  if (!mc?.registerTool) throw new Error('Native WebMCP unavailable');
  const register=mc.registerTool.bind(mc);
  const unpack=r=>r?.content?JSON.parse(r.content.find(c=>c.type==='text').text):r;
  const pack=data=>({content:[{type:'text',text:JSON.stringify(data)}]});
  mc.registerTool=(descriptor,options)=>{
    const execute=descriptor.execute;
    let d={...descriptor};
    if(app==='ea'&&cfg.representation==='equivalent'){
      if(d.name==='check_availability') d.description='Read actual availability and update the visible wizard. Query date is a business-local calendar day. Returned days/date and open_slots are UTC calendar dates and UTC 24h HH:mm. Provider timezone identifies the business-local zone. Pass the returned UTC date and time to book_appointment.';
      if(d.name==='book_appointment'){
        d.description='Create one real appointment immediately. Requires explicit user permission and an open slot. date and time must be UTC, as returned by check_availability. The callback converts UTC to the business time zone for the original booking operation. Success navigates to confirmation. Do not repeat an uncertain submission.';
        d.inputSchema=structuredClone(d.inputSchema);
        d.inputSchema.properties.date.description='UTC calendar date YYYY-MM-DD from check_availability.';
        d.inputSchema.properties.time.description='UTC 24h HH:mm from check_availability.';
      }
    }
    d.execute=async(args,...rest)=>{
      let params=args;
      if(app==='ea'&&cfg.representation==='equivalent'&&d.name==='book_appointment'){
        const local=moment.utc(`${args.date} ${args.time}`,'YYYY-MM-DD HH:mm',true).tz(cfg.zone);
        if(!local.isValid())return pack({error:'Invalid UTC date/time. Use the returned open UTC slot.'});
        params={...args,date:local.format('YYYY-MM-DD'),time:local.format('HH:mm')};
      }
      const raw=await execute(params,...rest), data=unpack(raw);
      if(app==='medusa'&&d.name==='view_cart'&&data.cart){
        const cart=data.cart;
        // The upstream subtotal is aggregate, not item-only: label it correctly.
        if(Object.hasOwn(cart,'subtotal')){
          cart.subtotal_including_shipping=cart.subtotal;delete cart.subtotal;
          cart.subtotal_scope='aggregate including delivery; total is the all-in amount';
        }
        if(cfg.representation==='equivalent'&&sessionStorage.getItem('point2_v2_actor')==='1'){
          const amount=value=>Number(String(value).replace(/[^0-9.\-]/g,''));
          const item=cart.items.reduce((sum,line)=>sum+amount(line.line_total),0);
          const total=amount(cart.total);
          if(!Number.isFinite(item)||!Number.isFinite(total))throw new Error('Non-numeric actual cart components');
          cart.amount_components={items:item,delivery_and_other_charges:Math.round((total-item)*100)/100,
            currency:cart.currency_code??cart.currency??'eur',scope:'Non-overlapping components. Add items and delivery_and_other_charges exactly once for the full final order total, including taxes.'};
          delete cart.total;delete cart.subtotal_including_shipping;delete cart.subtotal_scope;
        }
        return pack(data);
      }
      if(app==='ea'&&cfg.representation==='equivalent'&&d.name==='book_appointment'&&data.open_slots){
        data.timezone=cfg.zone;
        data.note='This rejected-write response reports remaining slots in the business-local timezone. Use check_availability for UTC slots before submitting.';
        return pack(data);
      }
      if(app==='ea'&&cfg.representation==='equivalent'&&d.name==='check_availability'&&data.days){
        data.days=data.days.map(day=>{
          const dates=new Set();
          const slots=(day.open_slots||[]).map(time=>{
            const utc=moment.tz(`${day.date} ${time}`,'YYYY-MM-DD HH:mm',cfg.zone).utc();
            dates.add(utc.format('YYYY-MM-DD'));return utc.format('HH:mm');
          });
          if(dates.size>1)throw new Error('One business day spans two UTC dates; grouped conversion required');
          return {...day,date:[...dates][0]||day.date,open_slots:slots};
        });
        data.timezone='UTC';data.business_timezone=cfg.zone;
        data.note='days/date and open_slots are UTC. Convert to the business timezone to match the user request. Submit the returned UTC date/time to book_appointment. UI slots remain business-local.';
        return pack(data);
      }
      return raw;
    };
    return register(d,options);
  };
})();
