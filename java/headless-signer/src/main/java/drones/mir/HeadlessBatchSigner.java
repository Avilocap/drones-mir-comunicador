package drones.mir;

import es.gob.afirma.signers.batch.client.BatchSigner;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyStore;
import java.security.KeyStore.PrivateKeyEntry;
import java.security.PrivateKey;
import java.security.cert.Certificate;
import java.util.Base64;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.Map;

public final class HeadlessBatchSigner {

    private static final String PASSWORD_ENV = "DRONES_HEADLESS_P12_PASSWORD";

    private HeadlessBatchSigner() {
    }

    public static void main(final String[] args) throws Exception {
        final ParsedArgs parsed = parseArgs(args);
        if (parsed.hasFlag("--help")) {
            printUsage();
            return;
        }
        if (parsed.hasFlag("--insecure")) {
            System.setProperty("disableSslChecks", "true");
        }

        final String password = System.getenv(PASSWORD_ENV);
        if (password == null) {
            throw new IllegalArgumentException("Missing " + PASSWORD_ENV);
        }

        final Path p12Path = Path.of(parsed.required("--p12"));
        final Path batchB64Path = Path.of(parsed.required("--batch-b64-file"));
        final String preSignUrl = parsed.required("--pre-sign-url");
        final String postSignUrl = parsed.required("--post-sign-url");
        final String alias = parsed.optional("--alias");

        final PrivateKeyEntry entry = loadPrivateKeyEntry(p12Path, password.toCharArray(), alias);
        final byte[] batch = Base64.getDecoder().decode(readTrimmed(batchB64Path));

        final String resultXml = BatchSigner.signXML(
                batch,
                preSignUrl,
                postSignUrl,
                entry.getCertificateChain(),
                entry.getPrivateKey()
        );

        final String resultB64 = Base64.getEncoder().encodeToString(
                resultXml.getBytes(StandardCharsets.UTF_8)
        );
        System.out.println(resultB64);
    }

    private static String readTrimmed(final Path path) throws IOException {
        return Files.readString(path, StandardCharsets.UTF_8).trim();
    }

    private static PrivateKeyEntry loadPrivateKeyEntry(
            final Path p12Path,
            final char[] password,
            final String alias
    ) throws Exception {
        final KeyStore keyStore = KeyStore.getInstance("PKCS12");
        try (InputStream input = Files.newInputStream(p12Path)) {
            keyStore.load(input, password);
        }

        if (alias != null && !alias.isBlank()) {
            return privateKeyEntryForAlias(keyStore, alias, password);
        }

        final Enumeration<String> aliases = keyStore.aliases();
        while (aliases.hasMoreElements()) {
            final String candidate = aliases.nextElement();
            if (keyStore.isKeyEntry(candidate)) {
                final KeyStore.Entry entry = keyStore.getEntry(
                        candidate,
                        new KeyStore.PasswordProtection(password)
                );
                if (entry instanceof PrivateKeyEntry) {
                    return (PrivateKeyEntry) entry;
                }
            }
        }
        throw new IllegalArgumentException("No private key entry found in P12");
    }

    private static PrivateKeyEntry privateKeyEntryForAlias(
            final KeyStore keyStore,
            final String alias,
            final char[] password
    ) throws Exception {
        if (!keyStore.containsAlias(alias)) {
            throw new IllegalArgumentException("Alias not found in P12");
        }
        final KeyStore.Entry entry = keyStore.getEntry(
                alias,
                new KeyStore.PasswordProtection(password)
        );
        if (!(entry instanceof PrivateKeyEntry)) {
            throw new IllegalArgumentException("Alias is not a private key entry");
        }

        final PrivateKeyEntry privateKeyEntry = (PrivateKeyEntry) entry;
        final PrivateKey privateKey = privateKeyEntry.getPrivateKey();
        final Certificate[] chain = privateKeyEntry.getCertificateChain();
        if (privateKey == null || chain == null || chain.length == 0) {
            throw new IllegalArgumentException("Alias does not contain a complete signing entry");
        }
        return privateKeyEntry;
    }

    private static ParsedArgs parseArgs(final String[] args) {
        final Map<String, String> values = new HashMap<>();
        final Map<String, Boolean> flags = new HashMap<>();
        for (int index = 0; index < args.length; index++) {
            final String arg = args[index];
            if ("--help".equals(arg) || "--insecure".equals(arg)) {
                flags.put(arg, Boolean.TRUE);
                continue;
            }
            if (!arg.startsWith("--")) {
                throw new IllegalArgumentException("Unexpected argument");
            }
            if (index + 1 >= args.length) {
                throw new IllegalArgumentException("Missing value for " + arg);
            }
            values.put(arg, args[++index]);
        }
        return new ParsedArgs(values, flags);
    }

    private static void printUsage() {
        System.out.println(
                "Usage: java ... drones.mir.HeadlessBatchSigner "
                        + "--p12 PATH --batch-b64-file PATH "
                        + "--pre-sign-url URL --post-sign-url URL [--alias ALIAS] [--insecure]"
        );
    }

    private static final class ParsedArgs {
        private final Map<String, String> values;
        private final Map<String, Boolean> flags;

        private ParsedArgs(final Map<String, String> values, final Map<String, Boolean> flags) {
            this.values = values;
            this.flags = flags;
        }

        private String required(final String name) {
            final String value = values.get(name);
            if (value == null || value.isBlank()) {
                throw new IllegalArgumentException("Missing required argument " + name);
            }
            return value;
        }

        private String optional(final String name) {
            return values.get(name);
        }

        private boolean hasFlag(final String name) {
            return Boolean.TRUE.equals(flags.get(name));
        }
    }
}
