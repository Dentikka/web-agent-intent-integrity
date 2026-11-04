<?php
/** Bootstrap immutable local WP/WC code against a case-local synthetic DB. */
declare(strict_types=1);
$site=str_replace('\\','/',realpath($argv[1]) ?: '');
$case_root=str_replace('\\','/',realpath($argv[3]) ?: '');
$database=str_replace('\\','/',$argv[2]);
if (!$site || !$case_root || !str_ends_with($database,'/state.sqlite') || !str_starts_with($database,$case_root.'/')) {
    throw new RuntimeException('Invalid isolated runtime/database paths');
}
if (!is_file($site.'/wp-settings.php') || !is_file($database)) { throw new RuntimeException('Runtime/database missing'); }
if (ini_get('allow_url_fopen') || !in_array('mail',explode(',',ini_get('disable_functions')),true)) {
    throw new RuntimeException('Process network/mail isolation missing');
}
$_SERVER['HTTP_HOST']='night-shop.example.test';
$_SERVER['SERVER_NAME']='night-shop.example.test';
$_SERVER['SERVER_PORT']='80';
$_SERVER['REQUEST_URI']='/';
$_SERVER['REQUEST_METHOD']='GET';
$_SERVER['REMOTE_ADDR']='127.0.0.1';
$_SERVER['HTTP_USER_AGENT']='Synthetic-Local-Checkout-Audit';
error_reporting(E_ALL & ~E_DEPRECATED & ~E_USER_DEPRECATED);
define('DB_NAME','synthetic_night');define('DB_USER','synthetic_night');
define('DB_PASSWORD','');define('DB_HOST','localhost');
define('DB_CHARSET','utf8mb4');define('DB_COLLATE','');
define('DB_ENGINE','sqlite');define('DB_PATH',$database);
define('WP_HOME','http://night-shop.example.test');define('WP_SITEURL','http://night-shop.example.test');
define('WP_CONTENT_DIR',$site.'/wp-content');
define('WP_CONTENT_URL','http://night-shop.example.test/wp-content');
define('WC_LOG_DIR',$case_root.'/wc-logs/');
define('WP_DEBUG',false);define('WP_DEBUG_DISPLAY',false);
define('DISABLE_WP_CRON',true);define('WP_HTTP_BLOCK_EXTERNAL',true);
define('AUTOMATIC_UPDATER_DISABLED',true);define('DISALLOW_FILE_MODS',true);
define('WP_ENVIRONMENT_TYPE','local');
foreach (['AUTH_KEY','SECURE_AUTH_KEY','LOGGED_IN_KEY','NONCE_KEY','AUTH_SALT','SECURE_AUTH_SALT','LOGGED_IN_SALT','NONCE_SALT'] as $key) {
    define($key,'SYNTHETIC-NIGHT-LOCAL-ONLY');
}
$table_prefix='wp_';define('ABSPATH',$site.'/');
if (!empty($input['authenticate_actor_before_init'])) {
    $auth_actor=$input['authenticate_actor_before_init'];
    if (!in_array($auth_actor,['a','b'],true)) { throw new RuntimeException('Unknown synthetic request identity'); }
    // CLI request fixture only: establish a case-local customer before WC
    // constructs its native session. No owner cookies or accounts are read.
    require_once ABSPATH.'wp-includes/plugin.php';
    add_filter('determine_current_user',function($current) use ($auth_actor) {
        $person=get_user_by('login','night_buyer_'.$auth_actor);
        return $person ? (int)$person->ID : $current;
    },PHP_INT_MAX);
}
fwrite(STDERR,"NIGHT_BOOTSTRAP wp-settings start\n");
require ABSPATH.'wp-settings.php';
fwrite(STDERR,"NIGHT_BOOTSTRAP wp-settings complete\n");
if (!class_exists('WC_Order') || WC_VERSION!=='9.9.5') { throw new RuntimeException('Unexpected WC runtime'); }
$network=wp_remote_get('https://blocked.example.test/probe');
if (!is_wp_error($network) || $network->get_error_code()!=='lab_network_blocked') {
    throw new RuntimeException('WordPress HTTP blocker not active');
}
if (apply_filters('pre_wp_mail',null,[])!==true) { throw new RuntimeException('Mail blocker not active'); }
fwrite(STDERR,"NIGHT_BOOTSTRAP isolation verified\n");

function night_emit(array $data): void {
    echo "\nNIGHT_RESULT:".json_encode($data,JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES)."\n";
}
function night_user(string $actor): void {
    if (!in_array($actor,['a','b'],true)) { throw new RuntimeException('Unknown synthetic actor'); }
    $login='night_buyer_'.$actor;
    $user=get_user_by('login',$login);
    if (!$user) {
        $id=wp_insert_user(['user_login'=>$login,'user_pass'=>'SYNTHETIC-NIGHT-ONLY-'.$actor,
            'user_email'=>$actor==='a' ? 'alex@night.example.test' : 'casey@night.example.test',
            'first_name'=>$actor==='a' ? 'Alex' : 'Casey','last_name'=>'Example','role'=>'customer']);
        if (is_wp_error($id)) { throw new RuntimeException($id->get_error_message()); }
    } else { $id=$user->ID; }
    wp_set_current_user((int)$id);
    if (!WC()->cart) { wc_load_cart(); }
    WC()->customer->set_billing_country('US');WC()->customer->set_billing_state('IL');
    WC()->customer->set_billing_postcode('00000');WC()->customer->set_billing_city('Test City');
    WC()->customer->set_shipping_country('US');WC()->customer->set_shipping_state('IL');
    WC()->customer->set_shipping_postcode('00000');WC()->customer->set_shipping_city('Test City');
    if (current_user_can('manage_woocommerce')) { throw new RuntimeException('Buyer unexpectedly has merchant permissions'); }
}
function night_snapshot(int $product_id, ?int $order_id, ?string $code): array {
    global $wpdb;
    $product=wc_get_product($product_id);
    $order=$order_id ? wc_get_order($order_id) : false;
    $coupon=$code ? new WC_Coupon($code) : null;
    $held_stock=(int)wc_get_held_stock_quantity($product);
    return ['product_id'=>$product_id,'stock_quantity'=>$product->get_stock_quantity(),
        'stock_managed'=>$product->managing_stock(),'held_stock'=>$held_stock,
        'order_id'=>$order ? $order->get_id() : null,'order_exists'=>(bool)$order,
        'status'=>$order ? $order->get_status() : null,'is_paid'=>$order ? $order->is_paid() : false,
        'payment_method'=>$order ? $order->get_payment_method() : null,
        'total'=>$order ? $order->get_total() : null,
        'transaction_id'=>$order ? $order->get_transaction_id() : null,
        'coupon_usage'=>$coupon ? $coupon->get_usage_count() : null,
        'coupon_tentative'=>$coupon ? (int)$coupon->get_data_store()->get_tentative_usage_count($coupon->get_id()) : null];
}
