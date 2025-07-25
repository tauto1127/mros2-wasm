set(APL_CMAKE_VERSION 3.5.1)
cmake_minimum_required(VERSION ${APL_CMAKE_VERSION})

# Set WASI-specific flags before project() call
if(CMAKE_TOOLCHAIN_FILE MATCHES "wasi-sdk")
  set(CMAKE_C_COMPILER_WORKS 1)
  set(CMAKE_CXX_COMPILER_WORKS 1)
  set(CMAKE_C_FLAGS_INIT "-Wno-unused-command-line-argument")
  set(CMAKE_CXX_FLAGS_INIT "-Wno-unused-command-line-argument")
endif()

project(mros2-wasm-project
  VERSION 1.0.0
  LANGUAGES CXX C
)

set(debug true)
# set(CMAKE_C_FLAGS "-std=gnu99")
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -g")
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -O0")
set(CMAKE_C_FLAGS  "${CMAKE_C_FLAGS} -Wall")
set(CMAKE_C_FLAGS  "${CMAKE_C_FLAGS} -Wunknown-pragmas")
set(CMAKE_C_FLAGS  "${CMAKE_C_FLAGS} -Wtrigraphs")
set(CMAKE_C_FLAGS  "${CMAKE_C_FLAGS} -Wimplicit-int")
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -g")
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -O0")

add_compile_definitions(OS_POSIX)
add_compile_definitions(osObjectsExternal)
add_compile_definitions(STM32F767xx)

message(STATUS "CMAKE_APPNAME=${CMAKE_APPNAME}")
set(MROS2_APPNAME ${CMAKE_APPNAME})

# CMSIS lib
add_subdirectory(cmsis-wasm)

set(cmsis_DIR "${PROJECT_SOURCE_DIR}/cmsis-wasm/public")
message(STATUS "cmsis_DIR=${cmsis_DIR}")
find_package(cmsis REQUIRED)

# LWIP lib
add_subdirectory(lwip-wasm)

set(lwip_DIR "${PROJECT_SOURCE_DIR}/lwip-wasm/public")
message(STATUS "lwip_DIR=${lwip_DIR}")
find_package(lwip REQUIRED)

# mros2 & embeddedRTPS lib
set(mros2_DIR "${PROJECT_SOURCE_DIR}/mros2")
message(STATUS "mros2_DIR=${mros2_DIR}")
add_library(mros2 INTERFACE)

set(CMAKE_OS_POSIX true)
add_subdirectory(mros2)

# Application combines (CMSIS LWIP EmbeddedRTPS mROS2)
include(workspace/${MROS2_APPNAME}/Filelists.cmake) 

function(COMPILE_TO_WASM SOURCE_FILE)
	get_filename_component(FILE_NAME ${SOURCE_FILE} NAME_WLE)

	set(WASM_MODULE ${FILE_NAME}.wasm)

	set(MAIN_TARGET_NAME MODULE_${FILE_NAME})
	add_executable(${MAIN_TARGET_NAME} ${SOURCE_FILE})
  	set_target_properties(${MAIN_TARGET_NAME} PROPERTIES OUTPUT_NAME ${WASM_MODULE})
    target_include_directories(${MAIN_TARGET_NAME}
      # CMSIS INCLUDES
      PRIVATE ${cmsis_DIR}/include

      # LWIP INCLUDES
      PRIVATE ${lwip_DIR}/include/posix
      PRIVATE ${lwip_DIR}/include/lwip
      PRIVATE ${lwip_DIR}/include/system

      # embeddedRTPS INCLUDES
      PRIVATE ${mros2_DIR}/include

      # mROS2 INCLUDES
      PRIVATE ${mros2_DIR}/include/mros2
      PRIVATE ${mros2_DIR}/include/mros2_msgs

      # rtps/config.h
      PRIVATE ${PROJECT_SOURCE_DIR}/include
      # app
      PRIVATE ${PROJECT_SOURCE_DIR}/workspace/${MROS2_APPNAME}
      PRIVATE ${PROJECT_SOURCE_DIR}/workspace/custom_msgs
    )
  	target_compile_options(${MAIN_TARGET_NAME} INTERFACE -pthread -nostdlib -z stack-size=5000)
  	target_link_libraries(${MAIN_TARGET_NAME} socket_wasi_ext mros2 lwip cmsis)
  	target_link_options(${MAIN_TARGET_NAME} PRIVATE
    	LINKER:--export=__heap_base,--export=__data_end
    	LINKER:--export=__wasm_call_ctors
    	LINKER:--shared-memory
      LINKER:--initial-memory=262144,--max-memory=262144
    	LINKER:--no-check-features
    	LINKER:--allow-undefined
    	LINKER:--export=malloc,--export=free,--export=calloc,--export=realloc
	)
endfunction()

compile_to_wasm(${apl_SRCS})
