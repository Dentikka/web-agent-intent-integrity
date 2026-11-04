<?php
/** Install only a new synthetic SQLite baseline; never load wp-config.php. */
declare(strict_types=1);
$site = str_replace('\\', '/', realpath($argv[1]) ?: '');
$out = str_replace('\\', '/', realpath($argv[2]) ?: '');
if (!$site || !$out || !is_file($site.'/wp-settings.php') || file_exists($out.'/state.sqlite')) {
    throw new RuntimeException('Require prepared source code and a fresh output directory');
}
foreach (['pdo_sqlite', 'mysqli', 'mbstring'] as $extension) {
    if (!extension_loaded($extension)) { throw new RuntimeException('Missing PHP extension: '.$extension); }
}
if (!is_file($site.'/wp-content/db.php') || !is_file($site.'/wp-content/mu-plugins/lab-isolation.php')) {
    throw new RuntimeException('SQLite drop-in and lab isolation plugin required');
}
$_SERVER['HTTP_HOST']='night-shop.example.test';
$_SERVER['SERVER_NAME']='night-shop.example.test';
$_SERVER['SERVER_PORT']='80';
$_SERVER['REQUEST_URI']='/';
$_SERVER['REQUEST_METHOD']='GET';
$_SERVER['REMOTE_ADDR']='127.0.0.1';
error_reporting(E_ALL & ~E_DEPRECATED & ~E_USER_DEPRECATED);
define('DB_NAME','synthetic_night'); define('DB_USER','synthetic_night');
define('DB_PASSWORD',''); define('DB_HOST','localhost');
define('DB_CHARSET','utf8mb4'); define('DB_COLLATE','');
define('DB_ENGINE','sqlite'); define('DB_PATH',$out.'/state.sqlite');
define('WP_HOME','http://night-shop.example.test');
define('WP_SITEURL','http://night-shop.example.test');
define('WP_CONTENT_DIR',$site.'/wp-content');
define('WP_CONTENT_URL','http://night-shop.example.test/wp-content');
define('WC_LOG_DIR',$out.'/wc-logs/');
define('WP_DEBUG',true); define('WP_DEBUG_DISPLAY',false);
define('WP_DEBUG_LOG',$out.'/prepare-debug.log');
define('WP_DISABLE_FATAL_ERROR_HANDLER',true);
define('DISABLE_WP_CRON',true); define('WP_HTTP_BLOCK_EXTERNAL',true);
define('AUTOMATIC_UPDATER_DISABLED',true); define('DISALLOW_FILE_MODS',true);
define('WP_ENVIRONMENT_TYPE','local'); define('WP_INSTALLING',true);
foreach (['AUTH_KEY','SECURE_AUTH_KEY','LOGGED_IN_KEY','NONCE_KEY','AUTH_SALT','SECURE_AUTH_SALT','LOGGED_IN_SALT','NONCE_SALT'] as $key) {
    define($key,'SYNTHETIC-NIGHT-LOCAL-ONLY');
}
$table_prefix='wp_'; define('ABSPATH',$site.'/');
require ABSPATH.'wp-settings.php';
require_once ABSPATH.'wp-admin/includes/upgrade.php';
// The pinned SQLite plugin's wp_install wrapper opens a transaction around
// MySQL DDL, although that DDL implicitly ends transactions in its translator.
// Use the same public WordPress schema/options/roles APIs without that wrapper.
require_once ABSPATH.'wp-admin/includes/schema.php';
foreach (explode(';',wp_get_db_schema()) as $query) {
    if (trim($query)!=='' && $wpdb->query(trim($query))===false) {
        throw new RuntimeException('Synthetic schema installation failed: '.$wpdb->last_error);
    }
}
populate_options(); populate_roles();
update_option('blogname','Synthetic cart lifecycle fixture');
update_option('admin_email','fixture-admin@example.test');
update_option('siteurl',WP_SITEURL); update_option('home',WP_HOME);
update_option('db_version',$wp_db_version);
$admin=wp_insert_user(['user_login'=>'fixture_admin','user_pass'=>'SYNTHETIC-FIXTURE-LOCAL-ONLY',
    'user_email'=>'fixture-admin@example.test','role'=>'administrator']);
if (is_wp_error($admin)) { throw new RuntimeException($admin->get_error_message()); }
require_once ABSPATH.'wp-admin/includes/plugin.php';
add_filter('upload_dir',static function($paths) use ($out) {
    $paths['basedir']=$out.'/uploads'; $paths['path']=$out.'/uploads';
    $paths['baseurl']='http://night-shop.example.test/fixture-uploads';
    $paths['url']=$paths['baseurl']; $paths['subdir']='';
    return $paths;
});
$activation=activate_plugin('woocommerce/woocommerce.php');
if (is_wp_error($activation)) {
    throw new RuntimeException($activation->get_error_message().' '.json_encode([
        'plugin_dir'=>WP_PLUGIN_DIR,'readable'=>is_readable(WP_PLUGIN_DIR.'/woocommerce/woocommerce.php'),
        'plugins'=>array_keys(get_plugins())]));
}
if (!class_exists('WC_Install') || WC_VERSION!=='9.9.5') { throw new RuntimeException('Require WooCommerce 9.9.5'); }
WC_Install::install();
update_option('woocommerce_currency','USD');
update_option('woocommerce_calc_taxes','no');
update_option('woocommerce_default_country','US:IL');
update_option('woocommerce_custom_orders_table_enabled','no');
update_option('blog_public','0');
$network=wp_remote_get('https://blocked.example.test/probe');
if (!is_wp_error($network) || $network->get_error_code()!=='lab_network_blocked'
    || apply_filters('pre_wp_mail',null,[])!==true) {
    throw new RuntimeException('Network/mail isolation failed');
}
echo "\nFIXTURE_RESULT:".json_encode(['wordpress'=>$wp_version,'woocommerce'=>WC_VERSION,
    'database'=>$out.'/state.sqlite','isolation'=>'verified'],JSON_THROW_ON_ERROR)."\n";
