<?php
/** Persistent research operation metadata over native, unpaid WooCommerce orders. */
declare(strict_types=1);
$input=json_decode(stream_get_contents(STDIN),true,512,JSON_THROW_ON_ERROR);
$input['authenticate_actor_before_init']='a';
require __DIR__.'/../cart_lifecycle/night_wc_bootstrap.php';
night_user('a');
$key='_binding_context_json';
if ($input['mode']==='init') {
    $context=$input['context'];
    $context['subject']=get_current_user_id();
    foreach (['current','previous','approval'] as $name) {
        $context[$name]['subject']=get_current_user_id();
    }
    update_option($key,json_encode($context,JSON_THROW_ON_ERROR));
} else {
    $context=json_decode((string)get_option($key),true,512,JSON_THROW_ON_ERROR);
    if ($input['mode']==='bind_order') {
        $role=$input['role'];
        if (!in_array($role,['current','history'],true)) { throw new RuntimeException('Unknown operation role'); }
        $operation=$context[$role==='current' ? 'current' : 'previous']['operation_id'];
        $order=wc_get_order((int)$input['order_id']);
        if (!$order || $order->get_customer_id()!==get_current_user_id() || $order->is_paid()) {
            throw new RuntimeException('Invalid synthetic unpaid order');
        }
        $order->update_meta_data('_binding_operation',$operation);
        $order->update_meta_data('_binding_role',$role);
        $order->save();
    } elseif ($input['mode']!=='read') { throw new RuntimeException('Unknown metadata mode'); }
}
$orders=[];
foreach (wc_get_orders(['limit'=>-1,'customer_id'=>get_current_user_id(),
    'meta_key'=>'_drift_episode','meta_value'=>$input['episode']]) as $order) {
    $items=[];
    foreach($order->get_items() as $item) {
        $items[]=['product_id'=>(int)$item->get_product_id(),'quantity'=>(int)$item->get_quantity()];
    }
    $orders[]=['order_id'=>$order->get_id(),'operation_id'=>$order->get_meta('_binding_operation'),
        'role'=>$order->get_meta('_binding_role'),'subject'=>$order->get_customer_id(),
        'items'=>$items,'currency'=>$order->get_currency(),
        'total_minor'=>(int)round((float)$order->get_total()*100),'paid'=>$order->is_paid()];
}
night_emit(['context'=>$context,'orders'=>$orders,'wc_version'=>WC_VERSION]);
