import socket

ip = input("entrez l'ip scannable : ")
portS_debut = int(input("entrez le port de scan de debut : "))
portS_fin = int(input("entrez le port de scan de fin : "))

print(f"\nScan de l'ip {ip} du port {portS_debut} au port {portS_fin} :\n")

for port in range(portS_debut, portS_fin + 1):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            result = sock.connect_ex((ip, port))
            if result == 0:
                print(f"Port {port} : ouvert")
            else:
                print(f"Port {port} : fermé")
    except socket.gaierror:
        print(f"Erreur: nom d'hôte invalide pour {ip}")
        break
    except KeyboardInterrupt:
        print("\nScan interrompu par l'utilisateur.")
        break