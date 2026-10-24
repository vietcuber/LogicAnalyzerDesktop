# STM32 Logic Analyzer Desktop

Ứng dụng Desktop Python để cấu hình capture, nhận và xem tín hiệu số 8 kênh từ
firmware STM32 qua USB CDC. Ứng dụng hiện được phát triển cho STM32F103C8T6.

> **Trạng thái:** Development build. Một số điều khiển như Stop, Trigger và
> Protocol Decoder chưa được triển khai hoàn chỉnh; xem mục
> [Giới hạn hiện tại](#giới-hạn-hiện-tại).

## Tính năng

- Chọn cổng COM, kết nối/ngắt kết nối và làm mới danh sách thiết bị.
- Cấu hình tần số lấy mẫu và số mẫu capture.
- Nhận dữ liệu Streaming hoặc Snapshot từ firmware và hiển thị tiến độ.
- Hiển thị waveform logic 8 kênh; phóng to, thu nhỏ, Fit và xóa dashboard.
- Bật/tắt Cursor để xem sample index, thời gian (nếu có metadata tần số) và
  giá trị mẫu.
- Bật/tắt Marker A/B, chọn kênh và snap marker vào cạnh để xem hướng cạnh,
  khoảng cách mẫu và khoảng thời gian.
- Ẩn/hiện kênh, đổi tên, kéo thả sắp xếp thứ tự và chỉnh khoảng cách dọc.
- Lưu và mở capture ở định dạng `.la`.
- Tạo waveform mô phỏng bằng **Test waveform** để thử giao diện mà không cần
  kết nối thiết bị.

## Yêu cầu

- Windows 10/11 (có thể chạy trên nền tảng khác nếu các thư viện phụ thuộc được
  hỗ trợ).
- Python 3.10 trở lên.
- Git (nếu clone dự án).
- Firmware Logic Analyzer đã nạp lên STM32 và thiết bị được máy tính nhận diện
  dưới dạng cổng COM để capture từ phần cứng.

## Cài đặt và chạy

Mở PowerShell tại thư mục dự án:

```powershell
git clone https://github.com/<your-username>/LogicAnalyzerDesktop.git
Set-Location LogicAnalyzerDesktop

py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m app.main
```

Nếu PowerShell không cho phép activate môi trường ảo, có thể gọi Python trong
môi trường ảo trực tiếp:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.main
```

## Kết nối và capture

1. Kết nối board STM32 với máy tính qua USB và chọn cổng COM trong ứng dụng.
2. Chọn tần số lấy mẫu và số mẫu, sau đó nhấn **Connect**.
3. Chờ firmware xác nhận cấu hình rồi nhấn **Start**.
4. Quan sát waveform và tiến độ capture. Sau khi capture hoàn tất, có thể dùng
   Cursor hoặc Markers A/B để đo thủ công.
5. Nhấn **Save** để lưu capture hoặc **Open** để mở một file đã lưu.

Tần số lấy mẫu được hỗ trợ:

- `1, 2, 5, 10, 20, 50, 100, 200, 500 Hz`
- `1, 2, 5, 10, 20, 50, 100, 200, 500 kHz`
- `1 MHz` và `2 MHz`

Số mẫu lựa chọn:

`100, 200, 500, 1.000, 2.000, 5.000, 10.000, 20.000, 50.000, 100.000`.

Ở tần số từ **500 kHz trở lên**, capture bị giới hạn tối đa **10.000 mẫu**.
Dưới 500 kHz, ứng dụng cho phép tối đa **100.000 mẫu** theo chế độ Streaming
của firmware.

## Điều khiển giao diện

- **Start / Stop:** Start bắt đầu capture. Stop hiện chưa khả dụng vì firmware
  chưa hỗ trợ lệnh dừng tương ứng.
- **Zoom + / Zoom - / Fit:** Điều chỉnh vùng thời gian đang xem.
- **Clear:** Xóa waveform và dữ liệu capture khỏi dashboard.
- **Cursor:** Hiện/ẩn một cursor dọc; phần đọc kết quả chỉ hiện khi Cursor bật.
- **Markers A/B:** Hiện/ẩn hai marker; chọn kênh để snap vào các cạnh tín hiệu.
  Phần chọn kênh và kết quả đo chỉ hiện khi Markers bật.
- **Channels:** Bỏ chọn để ẩn kênh; kéo giữ ở vùng tên kênh để đổi thứ tự; nhấp
  đúp tên để đổi tên.
- **Test waveform:** Hiển thị dữ liệu mô phỏng, không phải dữ liệu đo từ board.

## Giao tiếp firmware

Ứng dụng gửi lệnh ASCII qua cổng serial:

```text
CONFIGURE <frequency_hz> <sample_count>
START
```

Firmware trả dữ liệu theo packet nhị phân. Mỗi mẫu là một byte, với ánh xạ:

| Bit | Kênh |
| --- | --- |
| 0 | CH0 |
| 1 | CH1 |
| 2 | CH2 |
| 3 | CH3 |
| 4 | CH4 |
| 5 | CH5 |
| 6 | CH6 |
| 7 | CH7 |

Đổi tên, ẩn/hiện hoặc sắp xếp lại kênh chỉ thay đổi cách hiển thị; không thay
đổi ánh xạ bit với đầu vào vật lý. Ứng dụng và firmware phải dùng cùng định dạng
packet và các giá trị cấu hình được hỗ trợ.

## File capture `.la`

File `.la` là tài liệu JSON. Version 2 lưu:

- Tần số lấy mẫu, số mẫu và thời điểm capture.
- Dữ liệu mẫu được mã hóa Base64.
- Tên, trạng thái hiển thị, thứ tự các kênh và khoảng cách dọc.

Ứng dụng vẫn đọc file version 1. File version 1 không có bố cục kênh đã lưu nên
được mở theo bố cục hiện tại trong ứng dụng.

## Chạy kiểm thử

Từ thư mục dự án, chạy:

```powershell
python -m unittest discover -s tests
```

Các kiểm thử bao gồm parser packet, xử lý waveform, đọc/ghi file capture và một
số hành vi giao diện.

## Giới hạn hiện tại

- **Stop:** Nút hiện bị vô hiệu hóa; firmware chưa có lệnh Stop được hỗ trợ.
- **Trigger:** Chưa có cấu hình trigger trước capture.
- **Protocol Decoder:** Chưa có giải mã UART, I2C hoặc SPI.
- **Đo tự động:** Marker hỗ trợ đo thủ công khoảng cách giữa hai cạnh; ứng dụng
  chưa tự động báo cáo period, frequency, duty cycle hoặc pulse width.
- **Test waveform:** Chỉ tạo dữ liệu mô phỏng để kiểm tra giao diện.
- **Điện áp đầu vào:** Ứng dụng không xác nhận mức điện áp an toàn. Không nối
  tín hiệu vượt giới hạn điện áp của MCU vào các chân STM32; việc bảo vệ đầu vào
  phụ thuộc thiết kế phần cứng thực tế.

## Cấu trúc thư mục

```text
app/
  main.py             Điểm khởi chạy ứng dụng
  main_window.py      Giao diện và luồng thao tác chính
  device_worker.py    Giao tiếp serial trong worker thread
  protocol.py         Packet parser và định nghĩa giao thức
  capture_file.py     Đọc/ghi file .la
  waveform.py         Tiện ích xử lý waveform và cạnh
tests/                Kiểm thử tự động
requirements.txt      Các thư viện Python cần cài đặt
```
