cmake_minimum_required(VERSION 3.22.1)
project(ning_inference LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(BUILD_CLI OFF CACHE BOOL "" FORCE)
set(BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(WITH_MKL OFF CACHE BOOL "" FORCE)
set(WITH_CUDA OFF CACHE BOOL "" FORCE)
set(WITH_CUDNN OFF CACHE BOOL "" FORCE)
set(WITH_DNNL OFF CACHE BOOL "" FORCE)
set(WITH_OPENBLAS OFF CACHE BOOL "" FORCE)
set(WITH_ACCELERATE OFF CACHE BOOL "" FORCE)
set(WITH_RUY ON CACHE BOOL "" FORCE)
set(OPENMP_RUNTIME NONE CACHE STRING "" FORCE)
set(RUY_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(CPUINFO_BUILD_UNIT_TESTS OFF CACHE BOOL "" FORCE)
set(CPUINFO_BUILD_MOCK_TESTS OFF CACHE BOOL "" FORCE)
set(CPUINFO_BUILD_BENCHMARKS OFF CACHE BOOL "" FORCE)

include(FetchContent)
FetchContent_Declare(ctranslate2
    GIT_REPOSITORY https://github.com/OpenNMT/CTranslate2.git
    # CTranslate2 v4.6.0, including the exact revisions of its CPU dependencies.
    GIT_TAG 617405f4b050e994e829d527da6caa0e0030afe7
    GIT_SUBMODULES third_party/cpu_features third_party/ruy third_party/spdlog
    GIT_SUBMODULES_RECURSE TRUE
)
FetchContent_MakeAvailable(ctranslate2)
# Upstream unsets CMAKE_POSITION_INDEPENDENT_CODE after configuring Ruy.
set_target_properties(ctranslate2 PROPERTIES POSITION_INDEPENDENT_CODE ON)

# Android's libc does not expose pthread_setaffinity_np. Keep affinity disabled,
# as it is by default, using upstream's existing unsupported-platform branch.
file(READ "${ctranslate2_SOURCE_DIR}/src/thread_pool.cc" thread_pool_source)
string(REPLACE "#if !defined(__linux__) || defined(_OPENMP)"
    "#if !defined(__linux__) || defined(__ANDROID__) || defined(_OPENMP)"
    thread_pool_source "${thread_pool_source}")
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/thread_pool_android.cc" "${thread_pool_source}")
get_target_property(ctranslate2_sources ctranslate2 SOURCES)
list(REMOVE_ITEM ctranslate2_sources src/thread_pool.cc)
list(APPEND ctranslate2_sources "${CMAKE_CURRENT_BINARY_DIR}/thread_pool_android.cc")
set_property(TARGET ctranslate2 PROPERTY SOURCES "${ctranslate2_sources}")

set(SPM_ENABLE_SHARED OFF CACHE BOOL "" FORCE)
set(SPM_BUILD_TEST OFF CACHE BOOL "" FORCE)
set(SPM_ENABLE_TCMALLOC OFF CACHE BOOL "" FORCE)
set(SPM_ENABLE_NFKC_COMPILE OFF CACHE BOOL "" FORCE)
FetchContent_Declare(sentencepiece
    GIT_REPOSITORY https://github.com/google/sentencepiece.git
    # SentencePiece v0.2.1.
    GIT_TAG 31646a467d2051eb904e0b45de3a73e91fe1c1e3
)
FetchContent_GetProperties(sentencepiece)
if(NOT sentencepiece_POPULATED)
    FetchContent_Populate(sentencepiece)
    # Only the linked inference library is built; omit training tools and CLIs.
    add_subdirectory("${sentencepiece_SOURCE_DIR}" "${sentencepiece_BINARY_DIR}" EXCLUDE_FROM_ALL)
endif()
set_target_properties(sentencepiece-static PROPERTIES POSITION_INDEPENDENT_CODE ON)

add_library(ning_inference SHARED inference.cpp)
target_include_directories(ning_inference PRIVATE "${sentencepiece_SOURCE_DIR}/src")
target_link_libraries(ning_inference PRIVATE ctranslate2 sentencepiece-static)
target_compile_options(ning_inference PRIVATE -Wall -Wextra)
# CT2 thread-local destructors must remain mapped until their threads have exited.
target_link_options(ning_inference PRIVATE "-Wl,-z,max-page-size=16384" "-Wl,-z,nodelete")
