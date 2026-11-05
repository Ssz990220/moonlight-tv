target_sources(moonlight-lib PRIVATE
        keyboard_webos.c
        navkey_sdl_webos.c
        pbnjson_compat.c
        opus71_sdk.c
        opus71_root_bridge.c)
file(SHA256 "${CMAKE_SOURCE_DIR}/deploy/webos/libexec/opus71_root.py" OPUS71_ROOT_SHA)
file(SHA256 "${CMAKE_SOURCE_DIR}/deploy/webos/libexec/opus71_session.py" OPUS71_POLICY_SHA)
configure_file(opus71_root_hashes.h.in "${CMAKE_BINARY_DIR}/opus71_root_hashes.h" @ONLY)
set(MAT_DIR "${CMAKE_SOURCE_DIR}/deploy/webos/libexec/mat")
file(SHA256 "${MAT_DIR}/receiver.py" MAT_RECEIVER_SHA)
file(SHA256 "${MAT_DIR}/runtime.py" MAT_RUNTIME_SHA)
file(SHA256 "${MAT_DIR}/native_identity.py" MAT_NATIVE_SHA)
file(SHA256 "${MAT_DIR}/carrier.py" MAT_CARRIER_SHA)
file(WRITE "${CMAKE_BINARY_DIR}/mat-manifest.json"
    "{\"carrier.py\":\"${MAT_CARRIER_SHA}\",\"runtime.py\":\"${MAT_RUNTIME_SHA}\",\"native_identity.py\":\"${MAT_NATIVE_SHA}\"}\n")
file(SHA256 "${CMAKE_BINARY_DIR}/mat-manifest.json" MAT_MANIFEST_SHA)
configure_file(mat_receiver_hashes.h.in "${CMAKE_BINARY_DIR}/mat_receiver_hashes.h" @ONLY)
install(FILES "${CMAKE_BINARY_DIR}/mat-manifest.json" DESTINATION libexec/mat RENAME manifest.json)
pkg_check_modules(OPUS71_LS2 REQUIRED luna-service2 glib-2.0)
target_include_directories(moonlight-lib SYSTEM PRIVATE ${OPUS71_LS2_INCLUDE_DIRS})
target_link_libraries(moonlight-lib PUBLIC ${OPUS71_LS2_LIBRARIES})
target_sources(moonlight PRIVATE "${CMAKE_SOURCE_DIR}/src/app/stream/audio/mat_sdp.c")
target_link_options(moonlight PRIVATE "-Wl,--wrap=getSdpPayloadForStreamConfig")
