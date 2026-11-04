# Third-party components

The repository contains research adapters and actor/evaluation code. Upstream application installations are downloaded separately; this snapshot does not relicense their software.

| Component | Source and pinned version |
|---|---|
| WindTunnel reference integrations and capsules | https://github.com/nekuda-ai/WindTunnel ; exact application/runtime revisions are recorded in the associated execution evidence |
| WordPress | https://wordpress.org/wordpress-6.8.2.zip ; 6.8.2 |
| WooCommerce | https://downloads.wordpress.org/plugin/woocommerce.9.9.5.zip ; 9.9.5 |
| SQLite Database Integration | https://downloads.wordpress.org/plugin/sqlite-database-integration.3.1.0.zip ; 3.1.0 |
| EasyAppointments | https://github.com/alextselegidis/easyappointments ; container digest is retained in `studies/real_apps/src/realapp_v1/environment.py` |
| Medusa | https://github.com/medusajs/medusa ; reference storefront/capsule revisions are retained in the execution metadata |
| Playwright | https://github.com/microsoft/playwright-python ; version pinned in `requirements.txt` |

Upstream names are included to make the dependency provenance checkable. They identify third-party software, not the authors of this artifact. Application licenses and notices remain with the corresponding upstream distributions. No blanket license grant over third-party components is implied.
