#!/bin/bash

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
WASI_SDK_ROOT=${WASI_SDK_ROOT:-/opt/wasi-sdk-21}
WAMR_ROOT=${WAMR_ROOT:-${SCRIPT_DIR}/third_party/wamr}
CARTOGRAPHER_ROOT=${CARTOGRAPHER_ROOT:-${SCRIPT_DIR}/third_party/cartographer}
CARTOGRAPHER_LIBRARY_ROOT=${CARTOGRAPHER_LIBRARY_ROOT:-${SCRIPT_DIR}/third_party/cartographer-library}

if [ $# -gt 2 ] || [ $# -eq 0 ]
then
  echo "Usage: $0 {all|up|clean} appname"
  exit 1
fi

OPT=${1}
APPNAME=${2}

function clean_subdirectory()
{
  rm -rf ${1}/cmake_build
  rm -rf ${1}/public
}

if [ ${OPT} == "clean" ];
then
  echo "build operation is set to clean"
  rm -rf ./cmsis-wasm/Third_Party/FreeRTOS
  rm -rf ./lwip-wasm/Third_Party/STM32CubeF7
  clean_subdirectory cmsis-wasm
  clean_subdirectory lwip-wasm
  #clean_subdirectory mros2
  rm -rf ../library
  rm -rf cmake_build/
  echo "build clean is completed"
  exit 0
fi

if [ $# -ne 2 ]
then
  echo "Usage: $0 {all|up|clean} appname"
  exit 1
fi

if [ -d workspace/${APPNAME} ]
then
  :
else
  echo "ERROR: can not find appname=${APPNAME} on workspace/"
  exit 1
fi

export WAMR_ROOT


if [ -d cmake_build ]
then
  :
else
  mkdir cmake_build
fi

function download_files()
{
  local dir=${1}
  cd ${dir}
  bash Third_Party/download.bash
  if [ "${dir}" == "lwip-wasm" ]; then
    sed -i 's/^#define LWIP_PROVIDE_ERRNO/\/\* #define LWIP_PROVIDE_ERRNO \*\//g' Third_Party/STM32CubeF7/Middlewares/Third_Party/LwIP/system/arch/cc.h
  fi
  cd ..
}

function build_subdirectory()
{
  local dir=${1}/cmake_build
  if [ -d ${dir} ]
  then
    :
  else
    mkdir -p ${dir}
  fi
  cd ${dir}
  if [ $# -eq 1 ]
  then
    cmake .. -DWASI_SDK_PREFIX="${WASI_SDK_ROOT}" -DCMAKE_TOOLCHAIN_FILE="${WASI_SDK_ROOT}/share/cmake/wasi-sdk-pthread.cmake" -DCMAKE_SYSROOT="${LOCAL_SYSROOT}" -DWAMR_ROOT="${WAMR_ROOT}"
  else
    cmake .. -DWASI_SDK_PREFIX="${WASI_SDK_ROOT}" -DCMAKE_TOOLCHAIN_FILE="${WASI_SDK_ROOT}/share/cmake/wasi-sdk-pthread.cmake" -DCMAKE_SYSROOT="${LOCAL_SYSROOT}" -DWAMR_ROOT="${WAMR_ROOT}" -D ${2}
  fi
  make
  if [ -d ../public/include ]
  then
    :
  else
    make install
  fi
  cd ../..
}

# generate of header file for template functions of MsgType
function generate_template_functions()
{
	MROS2DIR=../mros2
	TEMPLATESGEN_FILE=${MROS2DIR}/mros2_header_generator/templates_generator.py

	echo "INFO: generate header file for template functions of MsgType"
	cd workspace
	python3 ${TEMPLATESGEN_FILE} ${APPNAME}
	if [ $? -eq 0 ];
	then
	  echo "INFO: header fille for template function of ${APPNAME}'s MsgType is successfully generated"
	else
	  echo "ERROR: failed to generate header fille for template function of ${APPNAME}'s MsgType"
	  exit 1
	fi
	cd ..
}

if [ ${OPT} = "all" ]
then
  LOCAL_SYSROOT="${HOME}/wasi-sysroot"
  if [ ! -d "${LOCAL_SYSROOT}" ]; then
    echo "Creating local copy of wasi-sysroot at ${LOCAL_SYSROOT}..."
    cp -r /opt/wasi-sdk-21/share/wasi-sysroot "${LOCAL_SYSROOT}"
    "${WASI_SDK_ROOT}/bin/llvm-ar" -d "${LOCAL_SYSROOT}/lib/wasm32-wasi/libc.a" dlmalloc.o
  fi
  download_files cmsis-wasm
  build_subdirectory cmsis-wasm
  download_files lwip-wasm
  build_subdirectory lwip-wasm
  generate_template_functions
  # build_subdirectory mros2 CMAKE_OS_POSIX=true
  cd cmake_build
  cmake .. -DWASI_SDK_PREFIX="${WASI_SDK_ROOT}" -DCMAKE_TOOLCHAIN_FILE="${WASI_SDK_ROOT}/share/cmake/wasi-sdk-pthread.cmake" -DCMAKE_SYSROOT="${LOCAL_SYSROOT}" -DWAMR_ROOT="${WAMR_ROOT}" -DCARTOGRAPHER_ROOT="${CARTOGRAPHER_ROOT}" -DCARTOGRAPHER_LIBRARY_ROOT="${CARTOGRAPHER_LIBRARY_ROOT}" -D CMAKE_APPNAME=${APPNAME} -D CMAKE_EXPORT_COMPILE_COMMANDS=1
  make
  cd ..
elif [ ${OPT} = "up" ]
then
  cd cmake_build
  cmake .. -D CMAKE_APPNAME=${APPNAME}
  make
  cd ..
else
  echo "ERROR: wrong operation ${OPT}"
  exit 1
fi
