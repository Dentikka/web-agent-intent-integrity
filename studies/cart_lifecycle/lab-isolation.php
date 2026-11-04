<?php
add_filter('pre_http_request', function(){ return new WP_Error('lab_network_blocked','Network disabled in isolated experiment'); }, 1);
add_filter('pre_wp_mail', '__return_true');
add_filter('woocommerce_allow_tracking', '__return_false');
add_filter('automatic_updater_disabled', '__return_true');
