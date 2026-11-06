.class public Lcom/lumia/keyinfoprobe/MainActivity;
.super Landroid/app/Activity;
.source "MainActivity.java"

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Landroid/app/Activity;-><init>()V
    return-void
.end method

.method protected onCreate(Landroid/os/Bundle;)V
    .locals 2
    invoke-super {p0, p1}, Landroid/app/Activity;->onCreate(Landroid/os/Bundle;)V
    new-instance v0, Landroid/widget/TextView;
    invoke-direct {v0, p0}, Landroid/widget/TextView;-><init>(Landroid/content/Context;)V
    const/4 v1, -0x1
    invoke-virtual {v0, v1}, Landroid/widget/TextView;->setTextColor(I)V
    const/high16 v1, -0x1000000
    invoke-virtual {v0, v1}, Landroid/widget/TextView;->setBackgroundColor(I)V
    invoke-static {}, Lcom/lumia/keyinfoprobe/MainActivity;->inspectKeyInfo()Ljava/lang/String;
    move-result-object v1
    invoke-virtual {v0, v1}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V
    invoke-virtual {p0, v0}, Landroid/app/Activity;->setContentView(Landroid/view/View;)V
    const-string v0, "LumiaKeyInfo"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method

.method private static inspectKeyInfo()Ljava/lang/String;
    .locals 12
    const-string v0, "lumia_keyinfo_diagnostic_temporary"
    const-string v1, "AndroidKeyStore"
    const/4 v2, 0x0
    :try_start
    invoke-static {v1}, Ljava/security/KeyStore;->getInstance(Ljava/lang/String;)Ljava/security/KeyStore;
    move-result-object v2
    const/4 v3, 0x0
    invoke-virtual {v2, v3}, Ljava/security/KeyStore;->load(Ljava/security/KeyStore$LoadStoreParameter;)V
    invoke-virtual {v2, v0}, Ljava/security/KeyStore;->deleteEntry(Ljava/lang/String;)V

    const-string v4, "AES"
    invoke-static {v4, v1}, Ljavax/crypto/KeyGenerator;->getInstance(Ljava/lang/String;Ljava/lang/String;)Ljavax/crypto/KeyGenerator;
    move-result-object v5
    new-instance v6, Landroid/security/keystore/KeyGenParameterSpec$Builder;
    const/4 v7, 0x3
    invoke-direct {v6, v0, v7}, Landroid/security/keystore/KeyGenParameterSpec$Builder;-><init>(Ljava/lang/String;I)V
    const/4 v7, 0x1
    invoke-virtual {v6, v7}, Landroid/security/keystore/KeyGenParameterSpec$Builder;->setUserAuthenticationRequired(Z)Landroid/security/keystore/KeyGenParameterSpec$Builder;
    move-result-object v6
    const/4 v7, 0x0
    const/4 v8, 0x1
    invoke-virtual {v6, v7, v8}, Landroid/security/keystore/KeyGenParameterSpec$Builder;->setUserAuthenticationParameters(II)Landroid/security/keystore/KeyGenParameterSpec$Builder;
    move-result-object v6
    invoke-virtual {v6}, Landroid/security/keystore/KeyGenParameterSpec$Builder;->build()Landroid/security/keystore/KeyGenParameterSpec;
    move-result-object v6
    invoke-virtual {v5, v6}, Ljavax/crypto/KeyGenerator;->init(Ljava/security/spec/AlgorithmParameterSpec;)V
    invoke-virtual {v5}, Ljavax/crypto/KeyGenerator;->generateKey()Ljavax/crypto/SecretKey;
    move-result-object v5
    invoke-interface {v5}, Ljavax/crypto/SecretKey;->getAlgorithm()Ljava/lang/String;
    move-result-object v4
    invoke-static {v4, v1}, Ljavax/crypto/SecretKeyFactory;->getInstance(Ljava/lang/String;Ljava/lang/String;)Ljavax/crypto/SecretKeyFactory;
    move-result-object v6
    const-class v7, Landroid/security/keystore/KeyInfo;
    invoke-virtual {v6, v5, v7}, Ljavax/crypto/SecretKeyFactory;->getKeySpec(Ljavax/crypto/SecretKey;Ljava/lang/Class;)Ljava/security/spec/KeySpec;
    move-result-object v7
    check-cast v7, Landroid/security/keystore/KeyInfo;

    new-instance v10, Ljava/lang/StringBuilder;
    invoke-direct {v10}, Ljava/lang/StringBuilder;-><init>()V
    const-string v11, "securityLevel="
    invoke-virtual {v10, v11}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v10
    invoke-virtual {v7}, Landroid/security/keystore/KeyInfo;->getSecurityLevel()I
    move-result v8
    invoke-virtual {v10, v8}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;
    move-result-object v10
    const-string v11, "\nisInsideSecureHardware="
    invoke-virtual {v10, v11}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v10
    invoke-virtual {v7}, Landroid/security/keystore/KeyInfo;->isInsideSecureHardware()Z
    move-result v8
    invoke-virtual {v10, v8}, Ljava/lang/StringBuilder;->append(Z)Ljava/lang/StringBuilder;
    move-result-object v10
    const-string v11, "\nauthRequired="
    invoke-virtual {v10, v11}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v10
    invoke-virtual {v7}, Landroid/security/keystore/KeyInfo;->isUserAuthenticationRequired()Z
    move-result v8
    invoke-virtual {v10, v8}, Ljava/lang/StringBuilder;->append(Z)Ljava/lang/StringBuilder;
    move-result-object v10
    const-string v11, "\nauthType="
    invoke-virtual {v10, v11}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v10
    invoke-virtual {v7}, Landroid/security/keystore/KeyInfo;->getUserAuthenticationType()I
    move-result v8
    invoke-virtual {v10, v8}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;
    move-result-object v10
    const-string v11, "\nauthEnforcedInSecureHardware="
    invoke-virtual {v10, v11}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v10
    invoke-virtual {v7}, Landroid/security/keystore/KeyInfo;->isUserAuthenticationRequirementEnforcedBySecureHardware()Z
    move-result v8
    invoke-virtual {v10, v8}, Ljava/lang/StringBuilder;->append(Z)Ljava/lang/StringBuilder;
    move-result-object v10
    invoke-virtual {v10}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v10
    :try_end
    .catch Ljava/lang/Exception; {:try_start .. :try_end} :catch_error

    :cleanup_start
    if-eqz v2, :return_result
    invoke-virtual {v2, v0}, Ljava/security/KeyStore;->deleteEntry(Ljava/lang/String;)V
    :cleanup_end
    goto :return_result
    .catch Ljava/lang/Exception; {:cleanup_start .. :cleanup_end} :cleanup_error

    :cleanup_error
    move-exception v3
    goto :return_result

    :catch_error
    move-exception v11
    new-instance v10, Ljava/lang/StringBuilder;
    invoke-direct {v10}, Ljava/lang/StringBuilder;-><init>()V
    const-string v3, "ERROR: "
    invoke-virtual {v10, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v10
    invoke-virtual {v11}, Ljava/lang/Exception;->toString()Ljava/lang/String;
    move-result-object v3
    invoke-virtual {v10, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v10
    invoke-virtual {v10}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v10
    if-eqz v2, :return_result
    :failed_cleanup_start
    invoke-virtual {v2, v0}, Ljava/security/KeyStore;->deleteEntry(Ljava/lang/String;)V
    :failed_cleanup_end
    goto :return_result
    .catch Ljava/lang/Exception; {:failed_cleanup_start .. :failed_cleanup_end} :failed_cleanup_error

    :failed_cleanup_error
    move-exception v3
    goto :return_result

    :return_result
    return-object v10
.end method
