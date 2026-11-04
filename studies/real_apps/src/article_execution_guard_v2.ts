import { completeCartWorkflow } from "@medusajs/medusa/core-flows"
import { ContainerRegistrationKeys, MedusaError } from "@medusajs/framework/utils"

// Validate the exact cart snapshot consumed by the original completion workflow.
// Never mutate the cart inside this hook.
completeCartWorkflow.hooks.validate(async ({ cart }: any, { container }: any) => {
  const db: any = container.resolve(ContainerRegistrationKeys.PG_CONNECTION)
  const found = await db.raw("SELECT document FROM research_contract WHERE subject=?", [cart.email])
  const con = found.rows[0]?.document
  if (!con) throw new MedusaError(MedusaError.Types.INVALID_DATA, "INTENT_GUARD: no approved contract")
  const items = cart.items ?? []
  const shipping = cart.shipping_methods ?? []
  const total = Number(cart.total)
  const allowed = con.authorized === true && con.operation === "create_order" &&
    cart.currency_code === con.currency && items.length === 1 &&
    items[0].variant_id === con.object_id && Number(items[0].quantity) === Number(con.quantity) &&
    shipping.length === 1 && shipping[0].name === con.shipping &&
    Number.isFinite(total) && total >= 0 && total <= Number(con.max_total)
  const snapshot = {
    cart_id: cart.id, subject: cart.email, currency: cart.currency_code,
    total, subtotal: cart.subtotal, item_total: cart.item_total,
    shipping_total: cart.shipping_total, tax_total: cart.tax_total,
    items: items.map((i: any) => ({ variant_id: i.variant_id, quantity: Number(i.quantity), unit_price: i.unit_price, total: i.total })),
    shipping: shipping.map((m: any) => ({ name: m.name, amount: m.amount, total: m.total }))
  }
  await db.raw("INSERT INTO research_execution_audit(cart_id,contract,snapshot,would_allow,enforced) VALUES(?,?::jsonb,?::jsonb,?,?)", [cart.id, JSON.stringify(con), JSON.stringify(snapshot), allowed, con.execution_guard_enabled === true])
  if (con.execution_guard_enabled === true && !allowed)
    throw new MedusaError(MedusaError.Types.INVALID_DATA, "INTENT_GUARD: actual full total, object, shipping or permission violates approved intent")
})
