target_sources(moonlight-lib PRIVATE
        keyboard_webos.c
        navkey_sdl_webos.c
        pbnjson_compat.c
        opus71_sdk.c
        opus71_root_bridge.c)
file(SHA256 "${CMAKE_SOURCE_DIR}/deploy/webos/libexec/opus71_root.py" OPUS71_ROOT_SHA)
file(SHA256 "${CMAKE_SOURCE_DIR}/deploy/webos/libexec/opus71_session.py" OPUS71_POLICY_SHA)
configure_file(opus71_root_hashes.h.in "${CMAKE_BINARY_DIR}/opus71_root_hashes.h" @ONLY)
pkg_check_modules(OPUS71_LS2 REQUIRED luna-service2)
target_include_directories(moonlight-lib SYSTEM PRIVATE ${OPUS71_LS2_INCLUDE_DIRS})
target_link_libraries(moonlight-lib PUBLIC ${OPUS71_LS2_LIBRARIES})
