# 智场同语硬件功能与指令总表

> 中控统一入口: `http://192.168.1.50:8798`. 表中的 `IP:PORT` 是中控实际下发、推送或设备接收的位置。

## 1. 中控标准工具

| 功能ID | 功能 | 操作 IP:PORT | 命令 | 格式 | 指令类型 | 含义 |
|---|---|---|---|---|---|---|
| `g1_safety_check` | 安全预检查 | 192.168.1.104:8731 /api/g1/execute; /api/devices/unitree_g1/commands poll | `{"primitive":"unitree_sdk_call","source_primitive":"safety_check","layer":"bridge","client":"SafetyGuard","method":"CheckPreconditions","args":{"dry_run":true,"min_human_distance_m":0.8,"speed_limit_mps":0.25}}` | JSON DeviceCommand | `g1.unitree_sdk_sequence.step` | 检查调试模式、人距、限速和急停状态。 |
| `g1_speak_notice` | 语音播报意图 | 192.168.1.104:8731 /api/g1/execute; /api/devices/unitree_g1/commands poll | `{"primitive":"unitree_sdk_call","source_primitive":"speak","layer":"onboard_io","client":"AudioClient","method":"TtsMaker","args":{"text_cn":"检测到热感上升，我将启动清凉联动并递送冰水。","speaker_id":0}}` | JSON DeviceCommand | `g1.unitree_sdk_sequence.step` | G1 在动作前播报当前行动意图。 |
| `g1_move_probe` | 短程动作探针 | 192.168.1.104:8731 /api/g1/execute; /api/devices/unitree_g1/commands poll | `{"primitive":"unitree_sdk_call","source_primitive":"move_probe","layer":"unitree_high_level","client":"LocoClient","method":"SetVelocity","args":{"vx":0.15,"vy":0,"omega":0,"duration":1.2,"dry_run_only":true}}` | JSON DeviceCommand | `g1.unitree_sdk_sequence.step` | 用于校园网和 SDK 桥接测试的短程 dry-run 动作。 |
| `g1_navigate_water_station` | 导航至冰水点 | 192.168.1.104:8731 /api/g1/execute; /api/devices/unitree_g1/commands poll | `{"primitive":"unitree_sdk_call","source_primitive":"navigate","layer":"bridge","client":"WaypointPlanner","method":"PlanThenLocoSetVelocity","args":{"waypoint":"ice_water_station","output_client":"LocoClient","output_method":"SetVelocity","dry_run_only":true}}` | JSON DeviceCommand | `g1.unitree_sdk_sequence.step` | 向预设冰水补给点移动。 |
| `g1_deliver_ice_water` | 递送冰水 | 192.168.1.104:8731 /api/g1/execute; /api/devices/unitree_g1/commands poll | `{"primitive":"unitree_sdk_call","source_primitive":"deliver_ice_water","layer":"station_tool","client":"WaterStationAdapter","method":"DeliverItem","args":{"item":"iced_bottled_water","handoff_zone":"cooling_handoff_01","dry_run_only":true}}` | JSON DeviceCommand | `g1.unitree_sdk_sequence.step` | 触发冰水补给适配器与递送意图。 |
| `g1_report_ready` | 回报完成 | 192.168.1.104:8731 /api/g1/execute; /api/devices/unitree_g1/commands poll | `{"primitive":"unitree_sdk_call","source_primitive":"report_ready","layer":"feedback","client":"FeedbackAdapter","method":"ReportReady","args":{"status":"ready"}}` | JSON DeviceCommand | `g1.unitree_sdk_sequence.step` | 向中枢 ACK 回路报告动作完成。 |
| `g1_heat_delivery_sequence` | 热感冰水递送链 | 192.168.1.104:8731 /api/g1/execute; /api/devices/unitree_g1/commands poll | `{"task_id":"manual_heat_delivery","scene_id":"heat_cooling_loop","speech_cn":"清凉补给已送达。","safety":{"dry_run":true,"speed_limit_mps":0.25,"min_human_distance_m":0.8},"sdk_sequence":[{"primitive":"unitree_sdk_call","source_primitive":"safety_check","layer":"bridge","client":"SafetyGuard","method":"CheckPreconditions","args":{"dry_run":true,"min_human_distance_m":0.8}},{"primitive":"unitree_sdk_call","source_primitive":"speak","layer":"onboard_io","client":"AudioClient","method":"TtsMaker","args":{"text_cn":"检测到热感上升，我将递送冰水。","speaker_id":0}},{"primitive":"unitree_sdk_call","source_primitive":"deliver_ice_water","layer":"station_tool","client":"WaterStationAdapter","method":"DeliverItem","args":{"item":"iced_bottled_water","dry_run_only":true}},{"primitive":"unitree_sdk_call","source_primitive":"report_ready","layer":"feedback","client":"FeedbackAdapter","method":"ReportReady","args":{"status":"ready"}}]}` | JSON DeviceCommand | `g1.unitree_sdk_sequence` | 清凉联动的完整 dry-run 动作链。 |
| `spray_mist_cooling` | 开启清凉喷雾 | 192.168.1.50:22001 /api/command | `{"task_id":"manual_spray_mist","op":"mist","zone":"cooling_zone_01","duration_sec":20,"intensity":0.45}` | JSON DeviceCommand | `spray.scene` | 在清凉区打开喷雾。 |
| `spray_stop` | 停止喷雾 | 192.168.1.50:22001 /api/command | `{"task_id":"manual_spray_stop","op":"stop","zone":"cooling_zone_01"}` | JSON DeviceCommand | `spray.stop` | 停止喷雾网关输出。 |
| `speaker_play_cocktail_01` | 播放 1 号音乐 | 中控轮询 /api/devices/speaker_gateway/commands; 预留 tcp_endpoint 12004 | `{"task_id":"manual_audio_01","op":"play","content_id":"audio_01_music_cocktail_loop","slot":1,"volume":0.62,"loop":true}` | JSON DeviceCommand | `speaker.play` | 播放音乐鸡尾酒循环音频。 |
| `speaker_play_cooling_notice_02` | 播放 2 号提示音 | 中控轮询 /api/devices/speaker_gateway/commands; 预留 tcp_endpoint 12004 | `{"task_id":"manual_audio_02","op":"play","content_id":"audio_02_cooling_notice","slot":2,"volume":0.58,"loop":false}` | JSON DeviceCommand | `speaker.play` | 播放清凉联动提示音。 |
| `speaker_stop` | 停止音响 | 中控轮询 /api/devices/speaker_gateway/commands; 预留 tcp_endpoint 12004 | `{"task_id":"manual_speaker_stop","op":"stop"}` | JSON DeviceCommand | `speaker.stop` | 停止音响播放。 |
| `projection_play_sound_wave_01` | 播放 1 号投影 | 中控轮询 /api/devices/projection_gateway/commands; 预留 tcp_endpoint 12005 | `{"task_id":"manual_video_01","op":"play","content_id":"video_01_sound_wave_visual","slot":1,"loop":true}` | JSON DeviceCommand | `projection.play` | 投射声波鸡尾酒视觉。 |
| `projection_play_cooling_02` | 播放 2 号投影 | 中控轮询 /api/devices/projection_gateway/commands; 预留 tcp_endpoint 12005 | `{"task_id":"manual_video_02","op":"play","content_id":"video_02_ice_water_ripple","slot":2,"loop":false}` | JSON DeviceCommand | `projection.play` | 投射清凉水波视觉。 |
| `projection_stop` | 停止投影 | 中控轮询 /api/devices/projection_gateway/commands; 预留 tcp_endpoint 12005 | `{"task_id":"manual_projection_stop","op":"stop"}` | JSON DeviceCommand | `projection.stop` | 停止投影播放。 |

## 2. 局域网原子指令

| 功能ID | 功能 | 操作 IP:PORT | 命令 | 格式 | 指令类型 | 含义 |
|---|---|---|---|---|---|---|
| `lan_cmd_001` | 电脑-图书馆横屏-打开 | `255.255.255.255:9` | `WOL#00-E0-00-15-10-0F` | WOL/UDP STR | `lan.wol` | 电脑-图书馆横屏-打开 |
| `lan_cmd_002` | 电脑-图书馆竖屏-打开 | `255.255.255.255:9` | `WOL#00-E0-00-15-05-93` | WOL/UDP STR | `lan.wol` | 电脑-图书馆竖屏-打开 |
| `lan_cmd_003` | 电脑-D楼投影-打开 | `255.255.255.255:9` | `WOL#00-E0-00-15-05-95` | WOL/UDP STR | `lan.wol` | 电脑-D楼投影-打开 |
| `lan_cmd_004` | 电脑-图书馆横屏-关闭 | `192.168.1.113:6018` | `shutdown#` | TCP STR | `lan.raw_command` | 电脑-图书馆横屏-关闭 |
| `lan_cmd_005` | 电脑-图书馆竖屏-关闭 | `192.168.1.111:6018` | `shutdown#` | TCP STR | `lan.raw_command` | 电脑-图书馆竖屏-关闭 |
| `lan_cmd_006` | 电脑-D楼投影-关闭 | `192.168.1.112:6018` | `shutdown#` | TCP STR | `lan.raw_command` | 电脑-D楼投影-关闭 |
| `lan_cmd_007` | 灯光-灯光-关闭 | `192.168.1.160:2430` | `53697564693131410A01FFFFFFFFFFFFFFFF01001B000103050064` | UDP HEX | `lan.raw_command` | 灯光-灯光-关闭 |
| `lan_cmd_008` | 灯光-灯光（蓝色）-打开 | `192.168.1.160:2430` | `53697564693131410A01FFFFFFFFFFFFFFFF01001B000103000064` | UDP HEX | `lan.raw_command` | 灯光-灯光（蓝色）-打开 |
| `lan_cmd_009` | 灯光-灯光（绿色）-打开 | `192.168.1.160:2430` | `53697564693131410A01FFFFFFFFFFFFFFFF01001B000103010064` | UDP HEX | `lan.raw_command` | 灯光-灯光（绿色）-打开 |
| `lan_cmd_010` | 灯光-灯光（白色）-打开 | `192.168.1.160:2430` | `53697564693131410A01FFFFFFFFFFFFFFFF01001B000103020064` | UDP HEX | `lan.raw_command` | 灯光-灯光（白色）-打开 |
| `lan_cmd_011` | 灯光-灯光（琥珀色）-打开 | `192.168.1.160:2430` | `53697564693131410A01FFFFFFFFFFFFFFFF01001B000103030064` | UDP HEX | `lan.raw_command` | 灯光-灯光（琥珀色）-打开 |
| `lan_cmd_012` | 投影机-图书馆竖屏-打开 | `192.168.1.101:20001` | `23 50 57 52 30 2C 31 21` | TCP HEX | `lan.raw_command` | 投影机-图书馆竖屏-打开 |
| `lan_cmd_013` | 投影机-图书馆横屏-打开 | `192.168.1.101:20002` | `23 50 57 52 30 2C 31 21` | TCP HEX | `lan.raw_command` | 投影机-图书馆横屏-打开 |
| `lan_cmd_014` | 投影机-D楼墙面-打开 | `192.168.1.101:20003` | `23 50 57 52 30 2C 31 21` | TCP HEX | `lan.raw_command` | 投影机-D楼墙面-打开 |
| `lan_cmd_015` | 播控-竖屏（总控）-播放 | `192.168.1.111:3011` | `videoPlay` | TCP STR | `lan.raw_command` | 播控-竖屏（总控）-播放 |
| `lan_cmd_016` | 播控-竖屏（总控）-暂停 | `192.168.1.111:3011` | `videoPause` | TCP STR | `lan.raw_command` | 播控-竖屏（总控）-暂停 |
| `lan_cmd_017` | 播控-竖屏（总控）-继续播放 | `192.168.1.111:3011` | `videoPlay` | TCP STR | `lan.raw_command` | 播控-竖屏（总控）-继续播放 |
| `lan_cmd_018` | 播控-竖屏（总控）-停止 | `192.168.1.111:3011` | `videoStop` | TCP STR | `lan.raw_command` | 播控-竖屏（总控）-停止 |
| `lan_cmd_019` | 投影机-图书馆竖屏-关闭 | `192.168.1.101:20001` | `23 50 57 52 30 2C 30 21` | TCP HEX | `lan.raw_command` | 投影机-图书馆竖屏-关闭 |
| `lan_cmd_020` | 投影机-图书馆横屏-关闭 | `192.168.1.101:20002` | `23 50 57 52 30 2C 30 21` | TCP HEX | `lan.raw_command` | 投影机-图书馆横屏-关闭 |
| `lan_cmd_021` | 投影机-D楼墙面-关闭 | `192.168.1.101:20003` | `23 50 57 52 30 2C 30 21` | TCP HEX | `lan.raw_command` | 投影机-D楼墙面-关闭 |
| `lan_cmd_022` | 灯光-灯光（交替）-打开 | `192.168.1.160:2430` | `53697564693131410A01FFFFFFFFFFFFFFFF01001B000103040064` | UDP HEX | `lan.raw_command` | 灯光-灯光（交替）-打开 |
| `lan_cmd_023` | 播控-横屏-播放 | `192.168.1.113:3011` | `videoPlay` | TCP STR | `lan.raw_command` | 播控-横屏-播放 |
| `lan_cmd_024` | 播控-横屏-暂停 | `192.168.1.113:3011` | `videoPause` | TCP STR | `lan.raw_command` | 播控-横屏-暂停 |
| `lan_cmd_025` | 播控-横屏-继续播放 | `192.168.1.113:3011` | `videoPlay` | TCP STR | `lan.raw_command` | 播控-横屏-继续播放 |
| `lan_cmd_026` | 播控-横屏-音量+ | `192.168.1.113:3011` | `InsSystemVol 5` | TCP STR | `lan.raw_command` | 播控-横屏-音量+ |
| `lan_cmd_027` | 播控-D楼-播放 | `192.168.1.112:3011` | `videoPlay` | TCP STR | `lan.raw_command` | 播控-D楼-播放 |
| `lan_cmd_028` | 播控-D楼-暂停 | `192.168.1.112:3011` | `videoPause` | TCP STR | `lan.raw_command` | 播控-D楼-暂停 |
| `lan_cmd_029` | 播控-D楼-继续播放 | `192.168.1.112:3011` | `videoPlay` | TCP STR | `lan.raw_command` | 播控-D楼-继续播放 |
| `lan_cmd_030` | 播控-D楼-停止 | `192.168.1.112:3011` | `videoStop` | TCP STR | `lan.raw_command` | 播控-D楼-停止 |
| `lan_cmd_031` | 播控-D楼-音量+ | `192.168.1.112:3011` | `InsSystemVol#5` | TCP STR | `lan.raw_command` | 播控-D楼-音量+ |
| `lan_cmd_032` | 播控-D楼-音量- | `192.168.1.112:3011` | `DesSystemVol 5` | TCP STR | `lan.raw_command` | 播控-D楼-音量- |
| `lan_cmd_033` | 播控-横屏-停止 | `192.168.1.113:3011` | `videoStop` | TCP STR | `lan.raw_command` | 播控-横屏-停止 |
| `lan_cmd_034` | 播控-横屏-音量- | `192.168.1.113:3011` | `DesSystemVol 5` | TCP STR | `lan.raw_command` | 播控-横屏-音量- |
| `lan_cmd_035` | 播控-竖屏（总控）-音量+ | `192.168.1.111:3011` | `InsSystemVol 5` | TCP STR | `lan.raw_command` | 播控-竖屏（总控）-音量+ |
| `lan_cmd_036` | 播控-竖屏（总控）-音量- | `192.168.1.111:3011` | `DesSystemVol 5` | TCP STR | `lan.raw_command` | 播控-竖屏（总控）-音量- |
| `lan_cmd_037` | 播控-竖屏（总控）-音量-静音 | `192.168.1.111:3011` | `MuteSystemVol 1` | TCP STR | `lan.raw_command` | 播控-竖屏（总控）-音量-静音 |
| `lan_cmd_038` | 播控-竖屏（总控）-音量-取消静音 | `192.168.1.111:3011` | `MuteSystemVol 0` | TCP STR | `lan.raw_command` | 播控-竖屏（总控）-音量-取消静音 |
| `lan_cmd_039` | 播控-横屏-音量-静音 | `192.168.1.113:3011` | `MuteSystemVol 1` | TCP STR | `lan.raw_command` | 播控-横屏-音量-静音 |
| `lan_cmd_040` | 播控-横屏-音量-取消静音 | `192.168.1.113:3011` | `MuteSystemVol 0` | TCP STR | `lan.raw_command` | 播控-横屏-音量-取消静音 |
| `lan_cmd_041` | 播控-D楼-音量-静音 | `192.168.1.112:3011` | `MuteSystemVol 1` | TCP STR | `lan.raw_command` | 播控-D楼-音量-静音 |
| `lan_cmd_042` | 播控-D楼-音量-取消静音 | `192.168.1.112:3011` | `MuteSystemVol 0` | TCP STR | `lan.raw_command` | 播控-D楼-音量-取消静音 |

## 3. G1 手臂动作表

| Action ID | 动作名 | 操作 IP:PORT | 命令 | 格式 | 指令类型 | 含义 |
|---|---|---|---|---|---|---|
| `0` | release arm | `192.168.1.104:8731 /api/g1/execute` | `G1ArmActionClient.ExecuteAction(action_map["release arm"])` | JSON DeviceCommand -> Python SDK2 call | `G1ArmActionClient.ExecuteAction` | 释放手臂/回到手臂释放状态 |
| `1` | shake hand | `192.168.1.104:8731 /api/g1/execute` | `ExecuteAction(action_map["shake hand"]); sleep(2); release arm` | JSON DeviceCommand -> Python SDK2 call | `G1ArmActionClient.ExecuteAction` | 握手后释放手臂 |
| `2` | high five | `192.168.1.104:8731 /api/g1/execute` | `ExecuteAction(action_map["high five"]); sleep(2); release arm` | JSON DeviceCommand -> Python SDK2 call | `G1ArmActionClient.ExecuteAction` | 击掌后释放手臂 |
| `3` | hug | `192.168.1.104:8731 /api/g1/execute` | `ExecuteAction(action_map["hug"]); sleep(2); release arm` | JSON DeviceCommand -> Python SDK2 call | `G1ArmActionClient.ExecuteAction` | 拥抱动作后释放手臂 |
| `4` | high wave | `192.168.1.104:8731 /api/g1/execute` | `ExecuteAction(action_map["high wave"])` | JSON DeviceCommand -> Python SDK2 call | `G1ArmActionClient.ExecuteAction` | 高位挥手 |
| `5` | clap | `192.168.1.104:8731 /api/g1/execute` | `ExecuteAction(action_map["clap"])` | JSON DeviceCommand -> Python SDK2 call | `G1ArmActionClient.ExecuteAction` | 鼓掌 |
| `6` | face wave | `192.168.1.104:8731 /api/g1/execute` | `ExecuteAction(action_map["face wave"])` | JSON DeviceCommand -> Python SDK2 call | `G1ArmActionClient.ExecuteAction` | 面前挥手 |
| `7` | left kiss | `192.168.1.104:8731 /api/g1/execute` | `ExecuteAction(action_map["left kiss"])` | JSON DeviceCommand -> Python SDK2 call | `G1ArmActionClient.ExecuteAction` | 左手飞吻 |
| `8` | heart | `192.168.1.104:8731 /api/g1/execute` | `ExecuteAction(action_map["heart"]); sleep(2); release arm` | JSON DeviceCommand -> Python SDK2 call | `G1ArmActionClient.ExecuteAction` | 比心后释放手臂 |
| `9` | right heart | `192.168.1.104:8731 /api/g1/execute` | `ExecuteAction(action_map["right heart"]); sleep(2); release arm` | JSON DeviceCommand -> Python SDK2 call | `G1ArmActionClient.ExecuteAction` | 右手比心后释放手臂 |
| `10` | hands up | `192.168.1.104:8731 /api/g1/execute` | `ExecuteAction(action_map["hands up"]); sleep(2); release arm` | JSON DeviceCommand -> Python SDK2 call | `G1ArmActionClient.ExecuteAction` | 双手举起后释放手臂 |
| `11` | x-ray | `192.168.1.104:8731 /api/g1/execute` | `ExecuteAction(action_map["x-ray"]); sleep(2); release arm` | JSON DeviceCommand -> Python SDK2 call | `G1ArmActionClient.ExecuteAction` | x-ray 动作后释放手臂 |
| `12` | right hand up | `192.168.1.104:8731 /api/g1/execute` | `ExecuteAction(action_map["right hand up"]); sleep(2); release arm` | JSON DeviceCommand -> Python SDK2 call | `G1ArmActionClient.ExecuteAction` | 右手举起后释放手臂 |
| `13` | reject | `192.168.1.104:8731 /api/g1/execute` | `ExecuteAction(action_map["reject"]); sleep(2); release arm` | JSON DeviceCommand -> Python SDK2 call | `G1ArmActionClient.ExecuteAction` | 拒绝动作后释放手臂 |
| `14` | right kiss | `192.168.1.104:8731 /api/g1/execute` | `ExecuteAction(action_map["right kiss"])` | JSON DeviceCommand -> Python SDK2 call | `G1ArmActionClient.ExecuteAction` | 右手飞吻 |
| `15` | two-hand kiss | `192.168.1.104:8731 /api/g1/execute` | `ExecuteAction(action_map["two-hand kiss"])` | JSON DeviceCommand -> Python SDK2 call | `G1ArmActionClient.ExecuteAction` | 双手飞吻 |
