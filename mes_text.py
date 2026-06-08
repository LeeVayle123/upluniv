ip = input("entrez l'adresse IP à scanner :")
Sp_debut = int(input("entrez le port à scanner de debut :"))
Sp_fin = int(input("entre le port à scanable de fin :"))

print(f"\n l'adresse {ip} sais doit scanner le port {Sp_debut} au port {Sp_fin}: \n")

for port in range(Sp_debut, Sp_fin + 1) :
    try:
        with socket.scket(socket_AF.INET , scket.SOCK_STREAM) as sock:
            socket.settimeout(0.5)
            result = socket.connect_ex((ip, port))
        if result == 0:
            print(f"port {port} Ouvert")
        else:
            printf(f"port {port} Fermé")
    except socket.gaierror:
        print(f"Erreur: nom d'hôte invalide pour {ip}")
        break
    except KeyboardInterrupt:
        print("\nScanne rompu par l'utiliusateur.")
        break



