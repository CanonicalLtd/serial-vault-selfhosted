import os

import charms.apt

from subprocess import (
    check_call,
    check_output,
    CalledProcessError
)
from charmhelpers.core.hookenv import (
    local_unit, 
    log, 
    relation_get, 
    relation_id, 
    relation_set, 
    related_units)
from charmhelpers.core import (
    templating,
    hookenv,
    host
)
from charmhelpers.fetch import (
    apt_upgrade
)
from charms.reactive import (
    hook, 
    is_state, 
    set_state
)
from charmhelpers.contrib.charmsupport import nrpe

PORTS = {
    'admin': {'open': 8081, 'close': [8080, 8082]},
    'signing': {'open': 8080, 'close': [8081, 8082]},
}

PROJECT = 'serial-vault'
SERVICE = '{}.service'.format(PROJECT)
AVAILABLE = '{}.available'.format(PROJECT)
ACTIVE = '{}.active'.format(PROJECT)

DATABASE_NAME = 'serialvault'

CONFDIR = '/etc/{}'.format(PROJECT)
ASSETSDIR = '/usr/share/{}'.format(PROJECT)
ADMIN_CMD = '{}-admin'.format(PROJECT)


@hook("install")
def install():
    """Charm install hook
    Initializes the environment as the Serial Vault installation is handled
    by the apt layer
    """
    if is_state(AVAILABLE):
        return

    # Open the relevant port for the service
    open_port()

    # Use rngd to speed up key generation
    initialize_rngd()

    # Build and deploy the application
    build_from_source()

    # Don't start until having db connection
    enable_service()

    hookenv.status_set('maintenance', 'Waiting for database')
    set_state(AVAILABLE)


@hook('config-changed')
def config_changed():
    rel_ids = list(hookenv.relation_ids('database'))
    if len(rel_ids) == 0:
        log("Database not ready yet... skipping it for now")
        return

    # Get the database settings
    db_id = rel_ids[0]
    relations = hookenv.relations()['database'][db_id]
    database = None
    for key, value in relations.items():
        if key.startswith('postgresql'):
            database = value
    if not database:
        log("Database not ready yet... skipping it for now")
        return

    # Open the relevant port for the service
    open_port()

    # Update the config file with the service_type and database settings
    update_config(database)

    # Restart the service
    restart_service()

    hookenv.status_set('active', '')
    set_state(ACTIVE)


@hook('database-relation-joined')
def db_relation_joined(*args):
    # Use a specific database name
    relation_set(database=DATABASE_NAME)


@hook('database-relation-changed')
def db_relation_changed(*args):
    configure_service()


@hook('website-relation-changed')
def website_relation_changed(*args):
    """
    Set the hostname and the port for reverse proxy relations
    """
    config = hookenv.config()
    port_config = PORTS.get(config['service_type'])
    if port_config:
        port = port_config['open']
    else:
        port = PORTS['signing']['open']

    relation_set(
        relation_id(), {'port': port, 'hostname': local_unit().split('/')[0]})


@hook('upgrade-charm')
def upgrade_charm():
    refresh_service()


@hook('nrpe-external-master-relation-changed')
def update_nrpe_checks(*args):
    nrpe_compat = nrpe.NRPE()
    conf = nrpe_compat.config
    check_http_params = conf.get('nagios_check_http_params')
    if check_http_params:
        nrpe_compat.add_check(
            shortname='vhost',
            description='Check Virtual Host',
            check_cmd='check_http %s' % check_http_params
        )
    nrpe_compat.write()

def refresh_service():
    hookenv.status_set('maintenance', 'Refresh the service')

    # Update the apt packages
    charms.apt.update()

    # Need to stop the service to be able to update it
    stop_service()

    build_from_source()

    hookenv.status_set('maintenance', 'Waiting for restart')


def configure_service():
    """Create service config file and place it in /usr/local/etc.
    Get the database settings and create the service config file
    """

    hookenv.status_set('maintenance', 'Configure the service')

    # Open the relevant port for the service
    open_port()

    database = get_database()
    if not database:
        return

    update_config(database)


def update_config(database):
    # Create the configuration file for the service in CONFDIR path
    create_settings(database)

    # Add the superusers to the system
    add_superusers()

    # Start the service
    start_service()

    hookenv.status_set('active', '')
    set_state(ACTIVE)


def get_database():
    if not relation_get('database'):
        log("Database not ready yet... skipping it for now")
        return None

    database = None
    for db_unit in related_units():
        # Make sure that we have the specific database for the serial vault
        if relation_get('database', db_unit) != DATABASE_NAME:
            continue

        remote_state = relation_get('state', db_unit)
        if remote_state in ('master', 'standalone'):
            database = relation_get(unit=db_unit)

    if not database:
        log("Database not ready yet... skipping it for now")
        hookenv.status_set('maintenance', 'Waiting for database')
        return None

    return database


def create_settings(postgres):
    hookenv.status_set('maintenance', 'Configuring service')
    config = hookenv.config()
    settings_path = '{}/{}'.format(CONFDIR, 'settings.yaml') 
    templating.render(
        source='settings.yaml',
        target=settings_path,
        context={
            'docRoot': ASSETSDIR,
            'keystore_secret': config['keystore_secret'],
            'service_type': config['service_type'],
            'csrf_auth_key': config['csrf_auth_key'],
            'db': postgres,
            'url_host': config['url_host'],
            'url_scheme': config['url_scheme'],
            'enable_user_auth': bool(config['enable_user_auth']),
            'jwt_secret': config['jwt_secret'],
        }
    )
    os.chmod(settings_path, 0o755)


def open_port():
    """
    Open the port that is requested for the service and close the others.
    """
    config = hookenv.config()
    port_config = PORTS.get(config['service_type'])
    if port_config:
        hookenv.open_port(port_config['open'], protocol='TCP')
        for port in port_config['close']:
            hookenv.close_port(port, protocol='TCP')


def enable_service():
    host.service('enable', SERVICE)


def start_service():
    host.service_start(SERVICE)


def restart_service():
    host.service_restart(SERVICE)


def stop_service():
    host.service_stop(SERVICE)


def add_superusers():
    config = hookenv.config()

    for u in config['superusers'].split(","):
        try:
            u = u.strip()
            check_call([
                ADMIN_CMD, 'user', 'add', u,
                '-n', u, '-r', 'superuser', '-e', '{}@example.com'.format(u)])
        except Exception:
            pass


def update_env():
    config = hookenv.config()
    env_vars_string = config['environment_variables']

    if env_vars_string:
        for env_var_string in env_vars_string.split(' '):
            key, value = env_var_string.split('=')
            value = dequote(value)
            log('setting env var {}'.format(key))
            os.environ[key] = value


def dequote(s):
    """
    If a string has single or double quotes around it, remove them.
    If a matching pair of quotes is not found, return the string unchanged.
    """

    if (
        s.startswith(("'", '"')) and s.endswith(("'", '"'))
        and (s[0] == s[-1])  # make sure the pair of quotes match
    ):
        s = s[1:-1]
    return s


def build_from_source():
    """
    Set up the Go environment and build the code from source.
    """
    hookenv.status_set('maintenance', 'Building application')
    config = hookenv.config()

    check_call(['sh', './scripts/install.sh', config['tagged_release']])

    hookenv.status_set('maintenance', 'Installation complete')


def initialize_rngd():
    """
    Use rngd to feed random data to the kernel. This speeds up signing key
    generation in snapd (from tens of minutes to seconds)
    """
    check_call(['rngd', '-r', '/dev/urandom'])
