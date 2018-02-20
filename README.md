# About
This charm installs a Serial Vault service, https://github.com/CanonicalLtd/serial-vault

The charm installs the Serial-Vault from a PPA hosted on launchpad.net.

# Install
After bootstrapping a juju environment, run:
```bash
juju deploy postgresql

juju deploy cs:~canonical-solutions/serial-vault-selfhosted serial-vault         # The signing service
juju add-relation serial-vault:database postgresql:db-admin

juju deploy cs:~canonical-solutions/serial-vault-selfhosted serial-vault-admin   # The admin service
juju add-relation serial-vault-admin:database postgresql:db-admin
juju config serial-vault-admin service_type=admin

# Expose the services
juju expose serial-vault         # port 8080
juju expose serial-vault-admin   # port 8081
```

Note: the db-admin relation is needed for the PostgreSQL service currently to avoid object ownership issues.