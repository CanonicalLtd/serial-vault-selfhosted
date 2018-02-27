#!/bin/sh

export GOPATH=`pwd`/go
PROJECT=serial-vault
PROJECT_PATH=github.com/CanonicalLtd
REPO=https://${PROJECT_PATH}/${PROJECT}

BIN_DIR=/usr/bin
LIB_DIR=/usr/lib/${PROJECT}
ASSETSDIR=/usr/share/${PROJECT}
CONFDIR=/etc/${PROJECT}
CRONDIR=/etc/cron.d
SERVICE=/lib/systemd/system

echo Make the Go paths
rm -rf ${GOPATH}
mkdir -p ${GOPATH}
mkdir -p ${GOPATH}/src/${PROJECT_PATH}
mkdir -p ${ASSETSDIR}
mkdir -p ${CONFDIR}
mkdir -p ${LIB_DIR}

echo Get the source code
cd ${GOPATH}/src/${PROJECT_PATH}
git clone ${REPO}
cd ${PROJECT}

# Checkout tagged release if requested
if [ -n "$1" ]; then
    echo Checkout tagged release $1
    git checkout tags/$1
fi

echo Get the dependencies
export PATH=$PATH:$GOPATH/bin
./get-deps.sh

echo Build the application
go install -v ./...

echo Install the application
cp ${GOPATH}/bin/* ${LIB_DIR}/
cp -r static ${ASSETSDIR}/
cp launchers/serial-vault* ${BIN_DIR}
cp launchers/cache-accounts-cron-job ${CRONDIR}/
cp settings.yaml ${CONFDIR}/
cp keystore/TestDeviceKey.asc ${CONFDIR}/
cp debian/serial-vault.service ${SERVICE}/

echo Update docRoot setting to point assets dir
sed -i 's/^docRoot:.*/docRoot: \"\/usr\/share\/serial-vault\"/' ${CONFDIR}/settings.yaml

echo Configure launchers to be used in systemd service
sed -i 's/{{[ ]*bindir[ ]*}}/\/usr\/lib\/serial-vault/g' ${BIN_DIR}/serial-vault
sed -i 's/{{[ ]*bindir[ ]*}}/\/usr\/lib\/serial-vault/g' ${BIN_DIR}/serial-vault-admin
sed -i 's/{{[ ]*confdir[ ]*}}/\/etc\/serial-vault/g' ${BIN_DIR}/serial-vault
sed -i 's/{{[ ]*confdir[ ]*}}/\/etc\/serial-vault/g' ${BIN_DIR}/serial-vault-admin

echo Restart the daemon for good measure
systemctl daemon-reload

exit 0
