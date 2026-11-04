<?php
/** Native WooCommerce cart/session/order operations on an episode-local clone. */
declare(strict_types=1);
$input=json_decode(stream_get_contents(STDIN),true,512,JSON_THROW_ON_ERROR);
$input['authenticate_actor_before_init']='a';
register_shutdown_function(static function(){
    if(!class_exists('WC_Order')) {
        fwrite(STDERR,json_encode(['plugin_dir'=>defined('WP_PLUGIN_DIR') ? WP_PLUGIN_DIR : null,
            'wc_file_readable'=>defined('WP_PLUGIN_DIR') && is_readable(WP_PLUGIN_DIR.'/woocommerce/woocommerce.php'),
            'wc_defined'=>defined('WC_VERSION') ? WC_VERSION : null]));
    }
});
require __DIR__.'/night_wc_bootstrap.php';
night_user('a');
$mode=$input['mode'];
$tag=$input['episode'];
if (!preg_match('/^[a-z0-9-]+$/D',$tag)) { throw new RuntimeException('Invalid episode'); }

function drift_cart(): array {
    WC()->cart->calculate_totals();
    $items=[];
    foreach(WC()->cart->get_cart() as $entry) {
        $items[]=['product_id'=>(int)$entry['product_id'],'name'=>$entry['data']->get_name(),
            'quantity'=>(int)$entry['quantity'],'unit_minor'=>(int)round((float)$entry['data']->get_price()*100)];
    }
    return ['items'=>$items,'total_minor'=>(int)round((float)WC()->cart->get_total('edit')*100),
        'currency'=>get_woocommerce_currency()];
}
function drift_orders(string $tag): array {
    $orders=wc_get_orders(['limit'=>-1,'customer_id'=>get_current_user_id(),
        'meta_key'=>'_drift_episode','meta_value'=>$tag]);
    $out=[];
    foreach($orders as $order) {
        $items=[];
        foreach($order->get_items() as $item) {
            $items[]=['product_id'=>(int)$item->get_product_id(),'quantity'=>(int)$item->get_quantity()];
        }
        $out[]=['order_id'=>$order->get_id(),'items'=>$items,'total_minor'=>(int)round((float)$order->get_total()*100),
            'currency'=>$order->get_currency(),'status'=>$order->get_status(),'paid'=>$order->is_paid()];
    }
    return $out;
}
if($mode==='setup') {
    update_option('woocommerce_currency','USD');
    update_option('woocommerce_calc_taxes','no');
    $products=[];
    foreach($input['products'] as $data) {
        $p=new WC_Product_Simple();$p->set_name($data['name']);$p->set_virtual(true);
        $p->set_regular_price(number_format($data['unit_minor']/100,2,'.',''));
        $p->set_manage_stock(false);$p->set_status('publish');$p->save();
        $products[]=['product_id'=>$p->get_id(),'name'=>$p->get_name(),'unit_minor'=>$data['unit_minor']];
    }
    update_option('_drift_catalog',$products);
    WC()->cart->empty_cart(true);
    if(!WC()->cart->add_to_cart($products[0]['product_id'],1)) {throw new RuntimeException('Cart initialization failed');}
    WC()->cart->calculate_totals();WC()->session->save_data();
    night_emit(['catalog'=>$products,'cart'=>drift_cart(),'orders'=>[],'wc_version'=>WC_VERSION]);exit;
}
$catalog=get_option('_drift_catalog');
if(!$catalog) {throw new RuntimeException('Missing setup');}
if($mode==='replace') {
    $id=(int)$input['product_id'];$quantity=(int)$input['quantity'];
    if(!in_array($id,array_column($catalog,'product_id'),true) || $quantity<1 || $quantity>5) {
        throw new RuntimeException('Invalid cart replacement');
    }
    WC()->cart->empty_cart(true);
    if(!WC()->cart->add_to_cart($id,$quantity)) {throw new RuntimeException('Native cart rejected replacement');}
    WC()->cart->calculate_totals();WC()->session->save_data();
} elseif($mode==='checkout') {
    $data=['billing_first_name'=>'Alex','billing_last_name'=>'Example','billing_email'=>'alex@night.example.test',
        'billing_country'=>'US','billing_state'=>'IL','billing_postcode'=>'00000','billing_city'=>'Test City',
        'billing_address_1'=>'Test Street 1','payment_method'=>'bacs'];
    $id=WC()->checkout()->create_order($data);
    if(is_wp_error($id)) {throw new RuntimeException($id->get_error_message());}
    $order=wc_get_order($id);$order->update_meta_data('_drift_episode',$tag);$order->save();
    // No gateway processing: only an unpaid native order is created.
    WC()->session->save_data();
} elseif(!in_array($mode,['read','orders'],true)) {throw new RuntimeException('Unknown mode');}
night_emit(['catalog'=>$catalog,'cart'=>drift_cart(),'orders'=>drift_orders($tag),'wc_version'=>WC_VERSION]);
