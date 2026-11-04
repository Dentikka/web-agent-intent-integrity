// Cache intervention uses an actually captured earlier application response.
// A normal document reload clears this document-scoped cached callback.
(() => {
  const app = __APP__;
  window.__p2Cache = null;
  const mc = document.modelContext ?? navigator.modelContext;
  if (!mc?.registerTool) throw new Error('Native WebMCP unavailable');
  const register = mc.registerTool.bind(mc);
  const unpack = r => r?.content ? JSON.parse(r.content.find(c=>c.type==='text').text) : r;
  const pack = data => ({content:[{type:'text',text:JSON.stringify(data)}]});
  mc.registerTool = (descriptor, options) => {
    const execute = descriptor.execute;
    return register({...descriptor,execute:async (...args) => {
      const data = await execute(...args);
      if (sessionStorage.getItem('point2_v2_actor') !== '1') return data;
      const target = app==='medusa'?'view_cart':'list_services';
      if (descriptor.name !== target) return data;
      if (window.__p2Cache) return pack(structuredClone(window.__p2Cache));
      if (app==='ea') {
        // The same public page provides a live catalogue, independently of
        // the retained UI document. No evaluator/SQL data enter the callback.
        const response=await fetch(App.Utils.Url.siteUrl('booking'),{credentials:'same-origin',cache:'no-store'});
        const html=await response.text();
        const match=html.match(/const vars = ([\s\S]*?);\s*return \(key\)/);
        if (!match) return pack({error:'Live public catalogue unavailable'});
        const live=JSON.parse(match[1]).webmcp_content.services;
        const result=unpack(data);
        for (const service of result.services||[]) {
          const current=live.find(s=>Number(s.id)===Number(service.id));
          if (current) service.price=`${Number(current.price).toFixed(2)} USD`;
        }
        return pack(result);
      }
      return data;
    }},options);
  };
})();
