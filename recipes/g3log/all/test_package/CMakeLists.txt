cmake_minimum_required(VERSION 3.15)
project(test_package LANGUAGES CXX)

find_package(g3log REQUIRED CONFIG)

add_executable(${PROJECT_NAME} test_package.cpp)
target_link_libraries(${PROJECT_NAME} PRIVATE g3log)
if(g3log_VERSION VERSION_LESS 2.0)
    target_compile_features(${PROJECT_NAME} PRIVATE cxx_std_14)
else()
    target_compile_features(${PROJECT_NAME} PRIVATE cxx_std_17)
endif()
