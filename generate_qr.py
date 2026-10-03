import qrcode

url = "https://swarmsync-prototype.onrender.com"

qr = qrcode.make(url)

qr.save("swarmsync_qr.png")

print("QR code generated successfully!")