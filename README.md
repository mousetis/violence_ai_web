# Violence AI Watch — Web giám sát camera nội bộ

Web app chạy local (một ứng dụng Flask gộp chung, không tách frontend/backend riêng), kết nối camera IP/CCTV qua RTSP, tự động ghi lại video + ảnh + mô tả khi phát hiện có bất thường, quản lý bằng đăng nhập, **không dùng database** — toàn bộ dữ liệu lưu dưới dạng file JSON + file video/ảnh trong thư mục `data/`.

## ⚠️ Quan trọng: phần "AI" hiện tại là placeholder

Hệ thống hiện dùng `MotionDetector` (trong `detection.py`) — một bộ phát hiện **chuyển động mạnh/đột ngột** bằng OpenCV (background subtraction), **KHÔNG PHẢI AI phân tích hành vi bạo lực thật**. Mục đích là để bạn kiểm tra toàn bộ luồng hệ thống (camera → phát hiện → cắt clip → lưu ảnh → hiển thị) trước khi có model AI thật.

Khi bạn có model thật (đã train từ bộ dữ liệu `Bo_tai_10000...`), cắm vào như sau:

1. Mở `detection.py`, tạo class mới kế thừa `BaseDetector`, ví dụ:
   ```python
   class ViolenceModelDetector(BaseDetector):
       def __init__(self, model_path):
           # load model đã train ở đây (TensorFlow / PyTorch / ONNX...)
           ...
       def process_frame(self, frame):
           # frame là ảnh numpy BGR (định dạng OpenCV)
           # chạy model, trả về DetectionResult(triggered, confidence, label, description)
           ...
   ```
2. Mở `camera_manager.py`, tìm dòng:
   ```python
   self.detector = MotionDetector(sensitivity=camera.get("sensitivity", 0.03))
   ```
   thay bằng `self.detector = ViolenceModelDetector(model_path="...")`.

Không cần sửa gì khác — phần web, quay clip, lưu trữ, giao diện sẽ tự hoạt động với detector mới.

Đây là cách "tích hợp AI vào web app" — web app tự kết nối camera VÀ tự chạy model. Nếu bạn muốn model AI chạy NGAY TRÊN/CẠNH CAMERA thay vì trong web app (camera tự quay + tự phát hiện, web app chỉ nhận kết quả), xem mục **"Kiến trúc Edge AI"** bên dưới — đó là hướng khuyến nghị khi bạn đã có (hoặc định dùng) camera/thiết bị tích hợp sẵn AI.

## Cài đặt

Yêu cầu: Python 3.9+ trở lên.

```bash
cd violence_ai_web
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
```

**Khuyến nghị cài thêm `ffmpeg`** (không bắt buộc, nhưng nên có): app dùng `ffmpeg` (nếu tìm thấy trong PATH) để chuyển clip cảnh báo sang chuẩn H.264 giúp phát trực tiếp mượt trên trình duyệt (Chrome không phát được codec mặc định của OpenCV). Nếu không có ffmpeg, video vẫn được lưu bình thường, chỉ là có thể cần mở bằng VLC thay vì xem trực tiếp trên web. Tải ffmpeg tại https://www.gyan.dev/ffmpeg/builds/ (giải nén rồi thêm thư mục `bin` vào PATH).

## Chạy

```bash
python app.py
```

Mở trình duyệt: `http://localhost:5000`

Đăng nhập lần đầu: **admin / admin123** — vào **Cài đặt** đổi mật khẩu ngay. Hoặc bấm **Đăng ký** ở trang đăng nhập để tạo tài khoản mới của riêng bạn.

## Tài khoản riêng cho từng người dùng

Mỗi tài khoản (kể cả tài khoản tự đăng ký) có camera và sự kiện cảnh báo **hoàn toàn riêng biệt** — không tài khoản nào xem/sửa/xoá được dữ liệu của tài khoản khác, kể cả biết ID camera/sự kiện. Tài khoản `admin` mặc định vẫn giữ camera/sự kiện đã có từ trước khi tính năng này ra đời.

## Giao diện: chế độ sáng / tối

Bấm nút ở cuối thanh menu bên trái để chuyển đổi chế độ sáng/tối — lựa chọn được ghi nhớ cho lần truy cập sau (lưu trong trình duyệt).

## Thêm camera

Vào **Camera → Thêm camera mới**, chọn 1 trong 2 loại nguồn:

- **Webcam máy tính**: dùng để test nhanh ngay trên máy đang chạy app, không cần thiết bị gì thêm. Nhập chỉ số webcam (mặc định `0` — đa số máy chỉ có 1 webcam nên để `0` là chạy được ngay; nếu có nhiều camera gắn ngoài, thử `1`, `2`...).
- **Camera IP / CCTV (RTSP)**: nhập đường dẫn dạng `rtsp://tên_đăng_nhập:mật_khẩu@địa_chỉ_ip:cổng/đường_dẫn` (lấy từ nhà sản xuất camera hoặc đầu ghi NVR/DVR của bạn).

App sẽ tự kết nối và tự thử lại nếu mất tín hiệu. Lưu ý: nếu webcam đang được ứng dụng khác dùng (Zoom, Google Meet, OBS...) thì app sẽ không mở được — hãy tắt ứng dụng đó trước.

**Ảnh bị lật/ngược?** Một số webcam (đặc biệt webcam laptop) trả về hình ảnh đã bị lật sẵn từ driver. Vào **Camera → Sửa** camera đó, chọn đúng **Chiều ảnh** (Lật ngang / Lật dọc / Xoay 180°) — thiết lập này áp dụng đồng nhất cho cả xem trực tiếp, video lưu và ảnh chụp, nên không bao giờ bị lệch nhau.

## Kiến trúc Edge AI (tuỳ chọn): camera tự phát hiện, web app chỉ nhận kết quả

Ngoài cách "web app tự kết nối + tự chạy detector" ở trên (gọi là chế độ **pull**, mặc định), hệ thống còn hỗ trợ chế độ **push**: một camera thông minh hoặc thiết bị AI gắn cạnh camera (Jetson, mini PC...) tự quay video và tự chạy model phát hiện bạo lực **độc lập với web app này**, chỉ gửi kết quả (video, ảnh, mô tả) về qua API. Đây là kiến trúc phù hợp khi:

- Camera cần tiếp tục phát hiện và ghi nhận **ngay cả khi web app này đang tắt** (dữ liệu được thiết bị AI giữ tạm và tự gửi lại khi web app hoạt động trở lại).
- Một "bộ não" AI (một thiết bị, một model) cần phục vụ **nhiều web app / nhiều nơi khác nhau** cùng lúc, thay vì bị khoá cứng vào 1 web app duy nhất.

### Cách bật chế độ Edge AI cho 1 camera

1. Vào **Camera → Thêm camera mới**, chọn **"Camera/thiết bị AI tự gửi dữ liệu (Edge AI)"** thay vì "Web app tự kết nối camera".
2. Vào trang chi tiết camera vừa tạo để lấy **camera_id**.
3. Vào **Cài đặt** để lấy **địa chỉ web app (base URL)** và **khoá API** (header `X-API-Key`, dùng chung cho mọi thiết bị Edge AI — có thể tạo khoá mới bất cứ lúc nào nếu nghi ngờ bị lộ).
4. Trên thiết bị AI, copy nguyên project này sang (cần `storage.py`, `camera_manager.py`, `detection.py`, `requirements.txt`, `detector_service.py`), cài `pip install -r requirements.txt`, rồi chạy `python detector_service.py` — lần đầu chạy sẽ tự tạo file `detector_config.json` mẫu, điền `web_app_url`, `api_key`, `camera.id` (lấy từ bước 2–3) vào rồi chạy lại.

`detector_service.py` **dùng lại nguyên logic quay/phát hiện hiện có** (`CameraWorker` trong `camera_manager.py` — cùng cơ chế đệm khung hình trước/sau sự kiện, cùng chỗ để cắm model AI thật vào `detection.py`), chỉ khác ở chỗ kết quả được **gửi qua HTTP** (`RemoteApiSink`) thay vì ghi thẳng vào file JSON của web app. Nếu web app tạm thời không phản hồi được, thiết bị sẽ tự xếp hàng chờ và gửi lại định kỳ — không mất dữ liệu.

### API dùng cho thiết bị Edge AI (xác thực bằng header `X-API-Key`)

- `POST /api/incidents` — tạo 1 sự kiện mới (form-data: `camera_id`, `label`, `confidence`, `description`, tuỳ chọn kèm file `image`/`video`).
- `POST /api/incidents/<id>/finish` — gửi video sau khi đã tạo sự kiện trước đó (trường hợp báo động trước, quay xong gửi sau).
- `POST /api/cameras/<id>/frame` — gửi khung hình JPEG mới nhất để hiển thị live view (tuỳ chọn).

Camera ở chế độ **pull** (mặc định, hành vi cũ) không bị ảnh hưởng gì bởi các API này — web app vẫn tự kết nối RTSP/webcam và tự chạy detector như trước.

## Cấu trúc dữ liệu (không dùng database)

```
data/
  users.json                 # tài khoản đăng nhập (mật khẩu đã băm)
  cameras.json                # danh sách camera đã cấu hình
  incidents/
    incidents.json            # danh sách sự kiện cảnh báo (metadata)
    videos/<id>.mp4            # video cắt tự động khi có cảnh báo
    images/<id>.jpg            # ảnh chụp tại thời điểm phát hiện
```

Muốn sao lưu hoặc chuyển sang máy khác: chỉ cần copy nguyên thư mục `data/`.

Mỗi bản ghi camera/sự kiện có thêm trường `deleted_at` (ISO timestamp hoặc `null`): `null` là đang hoạt động bình thường, có giá trị nghĩa là đang nằm trong **thùng rác** (xem mục bên dưới) — bản ghi và file video/ảnh liên quan vẫn còn nguyên trên đĩa cho tới khi được khôi phục hoặc xoá vĩnh viễn.

## Cách hoạt động khi có cảnh báo

Mỗi camera chạy trên 1 luồng riêng, liên tục:
1. Đọc khung hình từ RTSP, hiển thị trực tiếp (dạng MJPEG) lên trang web.
2. Chạy bộ phát hiện trên khung hình (mặc định mỗi 2 khung/lần để đỡ tốn CPU).
3. Khi phát hiện: tự lưu clip gồm **5 giây trước + 8 giây sau** thời điểm phát hiện, cùng 1 ảnh chụp, cùng mô tả — ghi vào `incidents.json`.
4. Sau khi báo động, có khoảng nghỉ 20 giây trước khi có thể báo tiếp (tránh spam liên tục).

Các con số này (5s/8s/20s, độ phân giải, số khung bỏ qua...) nằm ở đầu file `camera_manager.py`, có thể chỉnh trực tiếp.

Metadata của sự kiện được ghi vào `incidents.json` ngay khi bắt đầu quay (trạng thái `"recording"`), rồi cập nhật thành `"done"` sau khi xử lý xong (chuyển mã nếu có ffmpeg) — nên nếu server bị tắt đột ngột giữa chừng, sự kiện vẫn còn dấu vết đầy đủ thay vì bị mất hẳn.

## Thùng rác: xoá thường / khôi phục / xoá vĩnh viễn

Camera và sự kiện cảnh báo (kèm video + ảnh) đều có thể xoá theo 2 cách, chọn ngay khi bấm nút xoá:

- **Chuyển vào thùng rác** (mặc định, an toàn hơn): mục biến mất khỏi danh sách chính (và camera bị dừng quay), nhưng dữ liệu vẫn còn nguyên trên đĩa. Vào menu **Thùng rác** để xem lại, **Khôi phục** để dùng lại như cũ, hoặc **Xoá vĩnh viễn** thủ công bất cứ lúc nào. Nếu không làm gì, mục sẽ **tự động bị xoá vĩnh viễn sau 15 ngày**.
- **Xoá vĩnh viễn ngay**: xoá thẳng khỏi hệ thống (kể cả file video/ảnh), bỏ qua thùng rác — không thể hoàn tác.

Thùng rác (menu **Thùng rác** ở thanh bên) phân loại riêng theo **Camera** và **Sự kiện cảnh báo**, hiển thị số ngày còn lại trước khi tự xoá vĩnh viễn, và hỗ trợ chọn nhiều mục cùng lúc (tick chọn rồi **Khôi phục đã chọn** hoặc **Xoá vĩnh viễn đã chọn**).

Việc tự động dọn thùng rác chạy ngầm mỗi giờ (không cần mở trang Thùng rác), dựa trên mốc thời gian xoá (`deleted_at`) đã lưu sẵn ở mỗi camera/sự kiện — có thể chỉnh số ngày lưu trữ (`RETENTION_DAYS`, mặc định 15) ở đầu file `trash.py`. Thùng rác cũng tôn trọng việc mỗi tài khoản chỉ thấy và thao tác được trên dữ liệu của chính mình.

## Giới hạn hiện tại (nên biết trước khi dùng thật)

- **Bộ phát hiện là placeholder** — chỉ nhận biết chuyển động mạnh, không phân biệt được "bạo lực" với các chuyển động mạnh vô hại khác (chạy nhảy, vẫy tay...). Sẽ có báo động giả.
- **Hiệu năng**: nếu chạy nhiều camera độ phân giải cao cùng lúc trên máy yếu, có thể giật/chậm — cân nhắc giảm độ phân giải camera hoặc số lượng camera.
- **Không có mã hoá HTTPS / không có giới hạn số lần đăng nhập sai** — vì đây là app chạy nội bộ (local), nếu định mở ra ngoài Internet cần bổ sung thêm các lớp bảo mật này.
- **Chưa có phân quyền theo vai trò trong 1 tài khoản** (admin/nhân viên...) — mỗi tài khoản hiện là 1 silo dữ liệu độc lập ngang hàng, chưa hỗ trợ nhiều người cùng xem chung 1 tập camera với quyền khác nhau.
- **Khoá API của chế độ Edge AI dùng chung cho toàn hệ thống** (không tách riêng theo từng camera/thiết bị) — phù hợp môi trường nội bộ tin cậy; nếu triển khai rộng hơn nên cân nhắc khoá riêng theo thiết bị.

## Lưu ý pháp lý / đạo đức khi giám sát bằng camera

Giám sát bằng camera có gắn AI phát hiện hành vi cần tuân thủ quy định pháp luật về quyền riêng tư tại nơi lắp đặt (ví dụ: thông báo cho người bị quay biết khu vực có camera, không lắp ở nơi riêng tư như nhà vệ sinh/phòng thay đồ, giới hạn thời gian lưu trữ video, kiểm soát ai được xem dữ liệu nhạy cảm này). Bạn nên tự kiểm tra quy định áp dụng cho địa điểm/mục đích sử dụng cụ thể của mình.
