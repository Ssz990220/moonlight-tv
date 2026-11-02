target_sources(moonlight-lib PRIVATE
        keyboard_webos.c
        navkey_sdl_webos.c
        pbnjson_compat.c
        opus71_sdk.c
        opus71_root_bridge.c)
file(SHA256 "${CMAKE_SOURCE_DIR}/deploy/webos/libexec/opus71_root.py" OPUS71_ROOT_SHA)
file(SHA256 "${CMAKE_SOURCE_DIR}/deploy/webos/libexec/opus71_session.py" OPUS71_POLICY_SHA)
configure_file(opus71_root_hashes.h.in "${CMAKE_BINARY_DIR}/opus71_root_hashes.h" @ONLY)
