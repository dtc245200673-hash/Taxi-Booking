# Taxi Booking — Hệ thống quản lý đặt xe

Đồ án môn **Triển khai và Quản trị Hệ thống Phần mềm** (Đề 22).

Dự án xây dựng hệ thống quản lý đặt xe taxi dạng web, triển khai bằng Docker Compose. Người dùng có thể quản lý khách hàng, tài xế, chuyến đi và trạng thái chuyến đi. Hệ thống có reverse proxy, giám sát chỉ số, thu thập log và các biện pháp bảo mật cơ bản cho môi trường thực hành.

## 1. Công nghệ

| Thành phần | Công nghệ | Vai trò |
|---|---|---|
| Frontend | React | Giao diện quản lý |
| Web server / Reverse proxy | Nginx | Phục vụ giao diện và chuyển `/api/*` đến backend |
| Backend | Python, FastAPI | Xử lý nghiệp vụ, REST API, xuất metrics |
| Database | PostgreSQL 16 | Lưu khách hàng, tài xế, chuyến đi |
| Quản trị database | pgAdmin 4 | Kiểm tra và truy vấn dữ liệu |
| Metrics | Prometheus | Thu thập các chỉ số vận hành |
| Dashboard | Grafana | Quan sát metrics và log |
| Exporters | postgres-exporter, nginx-exporter, cAdvisor | Cung cấp metrics PostgreSQL, Nginx và tài nguyên container |
| Logging | Promtail + Loki | Thu thập, lưu trữ và truy vấn log |
| Orchestration | Docker Compose | Khởi chạy các dịch vụ liên quan |

## 2. Kiến trúc

```text
Trình duyệt (http://localhost:8080)
      |
      v
Nginx + React (web)
      |  /api/*
      v
FastAPI (backend) ------------------> PostgreSQL (postgres)
      |                                   ^
      |                                   |
      |                                pgAdmin
      |
      +--> /metrics --> Prometheus --> Grafana
      |
      +--> /app/logs/taxi-backend.log
                           |
                    shared volume taxi_logs
                           |
                        Promtail --> Loki --> Grafana Explore

PostgreSQL exporter, Nginx exporter và cAdvisor --> Prometheus
```

Mạng nội bộ Docker dùng tên `taxi-network`. Các dịch vụ có cổng publish ra máy chủ được cấu hình bind với `127.0.0.1` để phục vụ demo cục bộ.

## 3. Chức năng chính

- Quản lý khách hàng: xem danh sách, thêm khách hàng.
- Quản lý tài xế: xem danh sách, thêm tài xế.
- Quản lý chuyến đi: xem danh sách, tạo chuyến đi.
- Cập nhật trạng thái chuyến đi: `pending`, `assigned`, `in_progress`, `completed`, `cancelled`.
- Theo dõi tình trạng API, yêu cầu HTTP, thời gian xử lý, PostgreSQL, Nginx và tài nguyên Docker.
- Tra cứu nhật ký khởi động và các sự kiện như `trip_created`, `trip_status_changed`.

## 4. Cấu trúc thư mục

```text
TaxiBooking/
├── backend/                  # FastAPI, Dockerfile
├── database/
│   └── init.sql              # Khởi tạo các bảng
├── frontend/                 # React, Nginx config, Dockerfile
├── monitoring/
│   ├── prometheus/           # Cấu hình scrape metrics
│   ├── grafana/              # File JSON dashboard (nếu đã export)
│   ├── loki/                 # Cấu hình Loki
│   └── promtail/             # Cấu hình Promtail
├── docker-compose.yml
├── .env.example
└── README.md
```

## 5. Yêu cầu môi trường

- Windows với Docker Desktop và WSL 2, hoặc máy Linux có Docker Engine.
- Docker Compose.
- Git để clone mã nguồn.
- Các cổng localhost `8080`, `5050`, `5432`, `3000`, `9090`, `3100` không bị ứng dụng khác chiếm dụng.

## 6. Cài đặt và khởi động

### Bước 1: Lấy mã nguồn

```powershell
git clone https://github.com/dtc245200673-hash/Taxi-Booking.git
cd Taxi-Booking
```

### Bước 2: Tạo file môi trường

```powershell
Copy-Item .env.example .env
```

Mở `.env`, sửa các giá trị mật khẩu mẫu thành mật khẩu mạnh và thiết lập các biến:

```dotenv
POSTGRES_DB=taxi_booking
POSTGRES_USER=taxi_user
POSTGRES_PASSWORD=YOUR_STRONG_POSTGRES_PASSWORD
PGADMIN_EMAIL=admin@example.com
PGADMIN_PASSWORD=YOUR_STRONG_PGADMIN_PASSWORD
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=YOUR_STRONG_GRAFANA_PASSWORD
```

**Không commit `.env` lên GitHub.** File `.env.example` chỉ chứa tên biến và giá trị mẫu, không chứa bí mật thật.

### Bước 3: Khởi chạy toàn bộ dịch vụ

```powershell
docker compose config -q
docker compose up -d --build
docker compose ps
```

Lần đầu chạy, Docker cần tải các images. Database dùng script `database/init.sql` để tạo bảng khi volume PostgreSQL còn mới.

### Bước 4: Truy cập

| Dịch vụ | Địa chỉ từ máy chạy Docker |
|---|---|
| Website Taxi Booking | http://localhost:8080 |
| Kiểm tra API | http://localhost:8080/api/health |
| API docs FastAPI (qua nội bộ Docker hoặc cổng tạm) | `/docs` trên backend port 8000; không publish mặc định |
| pgAdmin | http://localhost:5050 |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |
| Loki readiness | http://localhost:3100/ready |

Kết nối PostgreSQL từ **pgAdmin chạy trong Docker** bằng `host=postgres`, `port=5432`, database/user/password theo `.env`. Không dùng `localhost` làm PostgreSQL host bên trong pgAdmin container.

### Bước 5: Dừng / khởi động lại

```powershell
docker compose down
# Khi sử dụng lại
docker compose up -d
```

Không chạy `docker compose down -v` nếu muốn giữ database, Grafana và dữ liệu volume.

## 7. Cơ sở dữ liệu

SQL ban đầu nằm tại `database/init.sql` với 3 bảng:

- `customers`: thông tin khách hàng (`id`, `full_name`, `phone`, `email`).
- `drivers`: thông tin tài xế (`id`, `full_name`, `phone`, `license_plate`, `is_available`).
- `trips`: chuyến xe (`customer_id`, `driver_id`, `pickup_address`, `destination_address`, `fare`, `status`, các mốc thời gian).

`trips.customer_id` tham chiếu `customers.id`; `trips.driver_id` tham chiếu `drivers.id`.

Truy vấn demo trên pgAdmin:

```sql
SELECT * FROM customers ORDER BY id DESC LIMIT 5;
SELECT * FROM drivers ORDER BY id DESC LIMIT 5;
SELECT * FROM trips ORDER BY id DESC LIMIT 5;
```

## 8. API chính

| Phương thức | Endpoint | Chức năng |
|---|---|---|
| GET | `/api/health` | Kiểm tra backend/database |
| GET, POST | `/api/customers` | Danh sách / thêm khách hàng |
| GET, POST | `/api/drivers` | Danh sách / thêm tài xế |
| GET, POST | `/api/trips` | Danh sách / tạo chuyến xe |
| PATCH | `/api/trips/{trip_id}/status` | Đổi trạng thái chuyến xe |
| GET | `/metrics` | Các chỉ số Prometheus trên backend |

Tại máy host, truy cập API thông qua `http://localhost:8080/api/...`.

## 9. Monitoring: Prometheus + Grafana

Prometheus thu thập các nhóm chỉ số từ backend, PostgreSQL exporter, Nginx exporter và cAdvisor. Dashboard **Taxi Booking - System Monitoring** gồm các panel:

1. Taxi Backend Status.
2. API Requests per Second.
3. Average API Response Time.
4. PostgreSQL Connections.
5. Nginx Active Connections.
6. Docker / cAdvisor Memory Overview.

Grafana sử dụng Prometheus data source: `http://prometheus:9090` (địa chỉ **bên trong mạng Docker**).

**Giới hạn môi trường:** cAdvisor trên Docker Desktop/WSL 2 có thể chỉ cung cấp một số thống kê cgroup tổng hợp, không đầy đủ nhãn theo từng container. Dùng `docker stats --no-stream` để bổ sung minh chứng sử dụng tài nguyên từng container.

## 10. Logging: Promtail + Loki + LogQL

Backend ghi sự kiện ứng dụng vào `/app/logs/taxi-backend.log`. Docker named volume `taxi_logs` được mount vào backend để ghi và vào Promtail theo chế độ chỉ đọc (`:ro`). Promtail gửi log đến Loki tại `http://loki:3100`.

Thêm Loki data source trên Grafana với URL **`http://loki:3100`**, sau đó vào **Explore** và thử ba câu LogQL:

```logql
{job="taxi-backend"}
```

```logql
{job="taxi-backend"} |= "trip_created"
```

```logql
{job="taxi-backend"} |= "trip_status_changed"
```

Kiểm tra trực tiếp file log:

```powershell
docker compose exec backend sh -c "tail -n 30 /app/logs/taxi-backend.log"
```

Có thể đối chiếu `trip_id` trong log với `id` của bảng `trips` trong PostgreSQL.

## 11. Hardening

Các biện pháp đã áp dụng/kiểm tra trong môi trường demo:

- Backend chạy bằng user thường (`uid=10001`, `appuser`) thay vì root.
- `no-new-privileges:true` trên backend nhằm hạn chế nâng đặc quyền.
- Nginx gửi `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Content-Security-Policy`.
- Các cổng publish chỉ bind trên loopback `127.0.0.1`; backend và các exporters không publish trực tiếp ra host.
- Promtail đọc shared log volume ở chế độ `:ro`, **không mount `/var/run/docker.sock`**.
- Mật khẩu cấu hình qua `.env` và không đưa lên Git.

Lệnh kiểm chứng:

```powershell
docker compose exec backend id
docker inspect taxi-backend --format '{{json .HostConfig.SecurityOpt}}'
curl.exe -I http://localhost:8080
docker compose ps
```

Các biện pháp này dành cho demo học tập, **không tương đương đánh giá bảo mật production**. Không mở public pgAdmin, Grafana, Loki hoặc PostgreSQL khi chưa bổ sung bảo vệ phù hợp.

## 12. Kịch bản demo

1. Truy cập `http://localhost:8080`, mở danh sách khách hàng và tài xế.
2. Tạo một chuyến xe; kiểm tra bản ghi mới trên giao diện.
3. Mở pgAdmin chạy `SELECT * FROM trips ORDER BY id DESC LIMIT 5;`.
4. Mở Grafana → Explore → Loki, lọc `trip_created` và đối chiếu `trip_id`.
5. Thay đổi trạng thái chuyến xe; lọc `trip_status_changed`.
6. Mở Grafana dashboard Prometheus để xem metrics, kiểm tra các exporter.
7. Mở Terminal trình bày chứng cứ Non-root, No New Privileges, headers và giới hạn cổng.

## 13. GitHub và lưu ý triển khai

Mã nguồn: https://github.com/dtc245200673-hash/Taxi-Booking

Lịch sử triển khai được phân chia thành các commit có ý nghĩa: ứng dụng và Nginx, monitoring Prometheus/Grafana, logging Loki/Promtail cùng hardening. Nhánh phát triển `develop` được đưa vào `main` thông qua Pull Request sau khi rà soát.

**Lưu ý:** Promtail là thành phần theo yêu cầu đề bài, nhưng đã hết vòng đời hỗ trợ chính thức. Cấu hình ở đây chỉ phục vụ đồ án/demo nội bộ; khi triển khai thực tế nên chuyển sang giải pháp thu thập log đang được hỗ trợ.
